/*
 * sync.c  —  Sincronização relativa de slots TDMA
 *
 * Implementação fiel ao algoritmo de Diogo Almeida (2023).
 * tdma_getDelay() portado directamente de tdma_utils.c do Diogo.
 *
 * Diferença face à versão anterior:
 *   Antes: delay = rx_time - sender_begin_ms  (impreciso)
 *   Agora: delay = cur_time - msg_position - ideal_slot_init  (preciso)
 *
 *   msg_position = timestamp - slot_begin_ms
 *   (posicao do pacote dentro do slot do emissor)
 *
 *   ideal_slot_init = quando o slot do emissor devia ter começado
 *   segundo o nosso relogio actual
 *
 * Miguel Almeida — FEUP 2025
 */

#include "sync.h"
#include "matrix.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <time.h>
#include <pthread.h>

/* ── estado interno ── */
static slot_limits_t    g_slot;
static uint8_t          g_slot_id;
static uint8_t          g_num_nodes;
static uint16_t         g_round_period_ms;
static pthread_mutex_t  g_mutex_slot  = PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t  g_mutex_delay = PTHREAD_MUTEX_INITIALIZER;

/* array de delays — posicao 0 nao e usada (como no Diogo) */
static float   g_delay_array[PKTDELAY_ARRAY_SIZE + 1];
static float   g_delay_sender[PKTDELAY_ARRAY_SIZE + 1];
static int64_t g_delay_count = 0;

/* ─────────────────────────────────────────────────────────────
 * get_current_round_time_ms()
 *
 * Tempo actual em ms dentro do round/frame.
 * Usa clock_gettime(CLOCK_REALTIME) — precisao de nanosegundos.
 * Equivalente a tdma_getCurrentRoundTimeD() do Diogo.
 * ───────────────────────────────────────────────────────────── */
static double get_current_round_time_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    int64_t sec  = (int64_t)ts.tv_sec;
    int64_t nsec = (int64_t)ts.tv_nsec;
    /* IGUAL ao tdma_getCurrentRoundTimeD() do Diogo: módulo em ms inteiros e
     * soma de volta a parte fracionária do ms (preserva precisão sub-ms). */
    double cur_time_ms =
        (double)((sec * 1000 + nsec / 1000000) % (int64_t)g_round_period_ms);
    cur_time_ms += -(double)(nsec / 1000000) + (nsec / 1000000.0);
    return cur_time_ms;
}

/* ─────────────────────────────────────────────────────────────
 * sync_init()
 * ───────────────────────────────────────────────────────────── */
void sync_init(uint8_t slot_id, uint8_t num_nodes, uint16_t round_period_ms) {
    g_slot_id        = slot_id;
    g_num_nodes      = num_nodes;
    g_round_period_ms = round_period_ms;

    uint16_t width_ms = round_period_ms / num_nodes;

    pthread_mutex_lock(&g_mutex_slot);
    g_slot.begin_ms = width_ms * (slot_id - 1);
    g_slot.end_ms   = g_slot.begin_ms + width_ms;
    g_slot.end_ms  %= round_period_ms;
    pthread_mutex_unlock(&g_mutex_slot);

    printf("[SYNC] Slot %u inicializado: [%u, %u] ms  (frame=%u ms  width=%u ms)\n",
           slot_id, g_slot.begin_ms, g_slot.end_ms, round_period_ms, width_ms);
}

/* ─────────────────────────────────────────────────────────────
 * sync_get_slot()
 * ───────────────────────────────────────────────────────────── */
slot_limits_t sync_get_slot(void) {
    pthread_mutex_lock(&g_mutex_slot);
    slot_limits_t copy = g_slot;
    pthread_mutex_unlock(&g_mutex_slot);
    return copy;
}

/* ─────────────────────────────────────────────────────────────
 * compute_delay()
 *
 * Portado directamente de tdma_getDelay() do Diogo Almeida (2023).
 *
 * Calcula o delay de propagacao de um pacote recebido:
 *
 *   msg_position = timestamp_sender - slot_begin_ms_sender
 *     (posicao do pacote dentro do slot do emissor em ms)
 *
 *   slot_difference = sender_slot_id - my_slot_id
 *     (+1 = slot seguinte, -1 = slot anterior)
 *
 *   ideal_slot_init_of_sender:
 *     se slot_difference == +1: ideal = my_slot.end_ms
 *     se slot_difference == -1: ideal = my_slot.begin_ms - sender_width
 *     outro:                    ideal = my_slot.begin_ms + diff*width + period
 *
 *   delay = cur_time_ms - msg_position - ideal_slot_init
 *
 * delay > 0: pacote chegou tarde  → avanca o slot
 * delay < 0: pacote chegou cedo   → (ignorado — so avancamos)
 * ───────────────────────────────────────────────────────────── */
static float compute_delay(uint8_t  sender_slot_id,
                            double   sender_timestamp_s,
                            uint16_t sender_begin_ms,
                            uint16_t sender_end_ms)
{
    (void)sender_end_ms;

    uint16_t width_ms = g_round_period_ms / g_num_nodes;

    /* msg_position: posicao do pacote dentro do slot do emissor */
    double sender_timestamp_ms = sender_timestamp_s * 1000.0;
    /* timestamp do emissor em ms dentro do round */
    double sender_ts_in_round = fmod(sender_timestamp_ms, (double)g_round_period_ms);
    /* msg_position: posição do pacote dentro do slot do emissor.
     * IGUAL ao tdma_getMsgPosition() do Diogo (sem clamp/sanitize extra). */
    float msg_position = (float)(sender_ts_in_round - (double)sender_begin_ms);
    if (msg_position < 0) msg_position += g_round_period_ms;

    /* slot_difference: +1=next, -1=prev */
    float slot_difference = (float)sender_slot_id - (float)g_slot_id;

    /* wrap-around para slots vizinhos no limite do frame */
    if (slot_difference == (float)(g_num_nodes - 1))
        slot_difference = -1.0f;
    else if (-slot_difference == (float)(g_num_nodes - 1))
        slot_difference = 1.0f;

    /* ideal_slot_init_of_sender segundo o nosso relogio */
    slot_limits_t myslot = sync_get_slot();
    float ideal_slot_init = 0.0f;

    if (slot_difference == 1.0f) {
        /* slot seguinte: devia comecar quando o nosso acaba */
        ideal_slot_init = (float)myslot.end_ms;
    } else if (slot_difference == -1.0f) {
        /* slot anterior: devia comecar antes do nosso */
        ideal_slot_init = (float)myslot.begin_ms - (float)width_ms;
    } else {
        /* slots mais distantes */
        ideal_slot_init = (float)myslot.begin_ms +
                          slot_difference * (float)width_ms +
                          (float)g_round_period_ms;
    }

    /* tempo actual no round */
    float cur_time_ms = (float)get_current_round_time_ms();

    /* delay = cur_time - msg_position - ideal_slot_init */
    float delay_ms = cur_time_ms - msg_position - ideal_slot_init;

    /* converte para positivo */
    while (delay_ms < 0)
        delay_ms += g_round_period_ms;

    delay_ms = fmodf(delay_ms, (float)g_round_period_ms);

    /* delay > meio round = chegou cedo (equivale a negativo) */
    if (delay_ms > g_round_period_ms / 2.0f)
        delay_ms -= g_round_period_ms;

    return delay_ms;
}

/* ─────────────────────────────────────────────────────────────
 * sync_record_delay()
 *
 * Chamado pelo RX para cada pacote MATRIX recebido.
 * Equivalente a tdma_recordPktDelay() do Diogo.
 * ───────────────────────────────────────────────────────────── */
void sync_record_delay(uint8_t  sender_slot_id,
                       double   sender_timestamp_s,
                       uint16_t sender_begin_ms,
                       uint16_t sender_end_ms,
                       uint16_t round_period_ms)
{
    (void)round_period_ms;

    float delay_ms = compute_delay(sender_slot_id, sender_timestamp_s,
                                   sender_begin_ms, sender_end_ms);

    pthread_mutex_lock(&g_mutex_delay);
    if (g_delay_count < PKTDELAY_ARRAY_SIZE) {
        g_delay_count++;
        /* posicao 0 nao e usada — como no Diogo */
        g_delay_array[g_delay_count]  = delay_ms;
        g_delay_sender[g_delay_count] = (float)sender_slot_id;
    }
    pthread_mutex_unlock(&g_mutex_delay);

    printf("[SYNC] delay registado: sender=%u  delay=%.2f ms  "
           "(cur=%.1f msg_pos calculada)\n",
           sender_slot_id, delay_ms,
           (float)get_current_round_time_ms());
}

/* ─────────────────────────────────────────────────────────────
 * computeMean()
 * ───────────────────────────────────────────────────────────── */
static float computeMean(float *arr, int n) {
    if (n == 0) return 0.0f;
    float sum = 0;
    for (int i = 0; i < n; i++) sum += arr[i];
    return sum / n;
}

/* ─────────────────────────────────────────────────────────────
 * shiftSlot()
 *
 * Equivalente a shiftSlot() do Diogo.
 * ───────────────────────────────────────────────────────────── */
static void shiftSlot(slot_limits_t *s, int32_t delta_ms) {
    uint16_t width_ms = g_round_period_ms / g_num_nodes;

    s->begin_ms = (uint16_t)((s->begin_ms + delta_ms + g_round_period_ms)
                              % g_round_period_ms);
    s->end_ms   = (uint16_t)((s->begin_ms + width_ms) % g_round_period_ms);
}

/* ─────────────────────────────────────────────────────────────
 * sync_adjust_slot()
 *
 * Chamado pelo TX no fim de cada round.
 * Equivalente a tdma_syncronizeSlot() do Diogo.
 * ───────────────────────────────────────────────────────────── */
void sync_adjust_slot(uint16_t round_period_ms) {
    (void)round_period_ms;

    /* copia segura do array de delays — como no Diogo */
    pthread_mutex_lock(&g_mutex_delay);
    int64_t count = g_delay_count;
    float tmp_array[PKTDELAY_ARRAY_SIZE + 1];
    float tmp_sender[PKTDELAY_ARRAY_SIZE + 1];
    memcpy(tmp_array,  (void*)(g_delay_array  + 1), sizeof(float) * count);
    memcpy(tmp_sender, (void*)(g_delay_sender + 1), sizeof(float) * count);
    g_delay_count = 0;  /* apaga delays — como no Diogo apos ajuste */
    pthread_mutex_unlock(&g_mutex_delay);

    if (count == 0) return;

    /* agrupa delays por no e calcula media — como no Diogo */
    float  aggByNode[MAX_NODES]                     = {0};
    float  delayByNode[MAX_NODES][PKTDELAY_ARRAY_SIZE] = {{0}};
    int    delayByNodeCounter[MAX_NODES]            = {0};
    int    isSender[MAX_NODES]                      = {0};

    for (int i = 0; i < count; i++) {
        uint8_t sender = (uint8_t)tmp_sender[i];
        if (sender == 0 || sender > MAX_NODES) continue;
        delayByNode[sender-1][delayByNodeCounter[sender-1]++] = tmp_array[i];
        isSender[sender-1] = 1;
    }

    for (int nj = 0; nj < MAX_NODES; nj++) {
        if (!isSender[nj]) continue;
        aggByNode[nj] = computeMean(delayByNode[nj], delayByNodeCounter[nj]);
        printf("[SYNC] Node %d: mean_delay=%.2f ms\n", nj+1, aggByNode[nj]);
    }

    /* delta = maximo das medias por no — como no Diogo */
    int32_t delta = 0;
    for (int nj = 0; nj < MAX_NODES; nj++) {
        if (!isSender[nj]) continue;
        if ((int32_t)aggByNode[nj] > delta)
            delta = (int32_t)aggByNode[nj];
    }

    /* limita a CSI% da largura do slot — como no Diogo */
    uint16_t width_ms = g_round_period_ms / g_num_nodes;
    int32_t lim = (int32_t)(SYNC_CSI * width_ms);
    if (lim < 1) lim = 1;
    if (delta > lim)  delta = lim;
    if (delta < 0)    delta = 0;

    /* componente aleatoria — como no Diogo (evita oscilacoes sincronizadas) */
    float rnd = (float)(rand() % 101) * 0.01f;
    delta = (int32_t)((float)delta * (0.8f + 0.2f * rnd));

    if (delta == 0) return;

    /* aplica shiftSlot — como no Diogo */
    pthread_mutex_lock(&g_mutex_slot);
    shiftSlot(&g_slot, delta);

    /* valida limites — como no Diogo */
    if (g_slot.begin_ms > g_round_period_ms ||
        g_slot.end_ms   > g_round_period_ms) {
        printf("[SYNC] ERRO: slot fora dos limites — reset\n");
        g_slot.begin_ms = (width_ms * (g_slot_id - 1)) % g_round_period_ms;
        g_slot.end_ms   = (g_slot.begin_ms + width_ms) % g_round_period_ms;
    }
    pthread_mutex_unlock(&g_mutex_slot);

    printf("[SYNC] Slot ajustado: delta=%d ms → [%u, %u] ms\n",
           delta, g_slot.begin_ms, g_slot.end_ms);
}

/* ─────────────────────────────────────────────────────────────
 * sync_slot_begin_us() / sync_slot_end_us()
 * ───────────────────────────────────────────────────────────── */
uint64_t sync_slot_begin_us(uint64_t now_us, uint16_t round_period_ms) {
    uint64_t round_us    = (uint64_t)round_period_ms * 1000;
    uint64_t frame_start = now_us - (now_us % round_us);
    slot_limits_t s      = sync_get_slot();
    return frame_start + (uint64_t)s.begin_ms * 1000;
}

uint64_t sync_slot_end_us(uint64_t now_us, uint16_t round_period_ms) {
    uint64_t round_us    = (uint64_t)round_period_ms * 1000;
    uint64_t frame_start = now_us - (now_us % round_us);
    slot_limits_t s      = sync_get_slot();
    return frame_start + (uint64_t)s.end_ms * 1000;
}

/* ─────────────────────────────────────────────────────────────
 * sync_in_slot()
 * ───────────────────────────────────────────────────────────── */
int sync_in_slot(uint64_t now_us, uint16_t round_period_ms) {
    uint64_t round_us = (uint64_t)round_period_ms * 1000;
    uint16_t t_ms     = (uint16_t)((now_us % round_us) / 1000);
    slot_limits_t s   = sync_get_slot();

    if (s.begin_ms <= s.end_ms)
        return (t_ms >= s.begin_ms && t_ms < s.end_ms);
    else
        return (t_ms >= s.begin_ms || t_ms < s.end_ms);
}