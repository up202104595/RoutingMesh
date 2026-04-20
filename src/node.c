/*
 * ═══════════════════════════════════════════════════════════════
 * sync.c  —  Sincronização relativa de slots TDMA
 *
 * Baseado no algoritmo do Diogo Almeida (2023).
 * ═══════════════════════════════════════════════════════════════
 */

#include "sync.h"
#include "matrix.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <pthread.h>

/* ── estado interno ── */
static slot_limits_t    g_slot;
static uint8_t          g_slot_id;
static uint8_t          g_num_nodes;
static pthread_mutex_t  g_mutex_slot  = PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t  g_mutex_delay = PTHREAD_MUTEX_INITIALIZER;

static float   g_delay_array[PKTDELAY_ARRAY_SIZE + 1];
static uint8_t g_delay_sender[PKTDELAY_ARRAY_SIZE + 1];
static int     g_delay_count = 0;

/* ─────────────────────────────────────────────────────────────
 * sync_init()
 * ───────────────────────────────────────────────────────────── */
void sync_init(uint8_t slot_id, uint8_t num_nodes, uint16_t round_period_ms) {
    g_slot_id   = slot_id;
    g_num_nodes = num_nodes;

    uint16_t width_ms = round_period_ms / num_nodes;

    pthread_mutex_lock(&g_mutex_slot);
    g_slot.begin_ms = width_ms * (slot_id - 1);
    g_slot.end_ms   = g_slot.begin_ms + width_ms - GUARD_INTERVAL_MS;
    g_slot.end_ms  %= round_period_ms;
    pthread_mutex_unlock(&g_mutex_slot);

    printf("[SYNC] Slot %u inicializado: [%u, %u] ms  (frame=%u ms)\n",
           slot_id, g_slot.begin_ms, g_slot.end_ms, round_period_ms);
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
 * Calcula o delay de um pacote recebido.
 *
 * O delay é a diferença entre quando o pacote chegou e quando
 * era esperado chegar, dado o slot do emissor.
 *
 * delay > 0 → pacote chegou tarde → emissor deve avançar o slot
 * delay < 0 → pacote chegou cedo → emissor deve atrasar o slot
 * ───────────────────────────────────────────────────────────── */
static float compute_delay(double rx_timestamp_s,
                            uint16_t sender_begin_ms,
                            uint16_t sender_end_ms,
                            uint16_t round_period_ms)
{
    /* tempo de recepção em ms dentro do frame */
    uint64_t rx_ms_abs = (uint64_t)(rx_timestamp_s * 1000.0);
    uint16_t rx_ms     = (uint16_t)(rx_ms_abs % round_period_ms);

    /* posição esperada do pacote: início do slot do emissor */
    uint16_t expected_ms = sender_begin_ms;

    /* delay = rx_ms - expected_ms (com wrap-around) */
    float delay_ms = (float)rx_ms - (float)expected_ms;

    /* wrap-around */
    while (delay_ms < 0)
        delay_ms += round_period_ms;
    delay_ms = fmodf(delay_ms, round_period_ms);

    /* delay > meio frame = chegou cedo (equivale a negativo) */
    if (delay_ms > round_period_ms / 2.0f)
        delay_ms -= round_period_ms;

    (void)sender_end_ms;
    return delay_ms;
}

/* ─────────────────────────────────────────────────────────────
 * sync_record_delay()
 *
 * Chamado pelo RX para cada pacote MATRIX recebido.
 * ───────────────────────────────────────────────────────────── */
void sync_record_delay(uint8_t  sender_slot_id,
                       double   rx_timestamp_s,
                       uint16_t sender_begin_ms,
                       uint16_t sender_end_ms,
                       uint16_t round_period_ms)
{
    /* só sincroniza com slots vizinhos (slot_id ± 1) */
    int diff = (int)sender_slot_id - (int)g_slot_id;
    if (diff != 1 && diff != -1 &&
        diff != (int)(g_num_nodes - 1) &&
        diff != -(int)(g_num_nodes - 1))
        return;

    float delay_ms = compute_delay(rx_timestamp_s, sender_begin_ms,
                                   sender_end_ms, round_period_ms);

    pthread_mutex_lock(&g_mutex_delay);
    if (g_delay_count < PKTDELAY_ARRAY_SIZE) {
        g_delay_count++;
        g_delay_array[g_delay_count]  = delay_ms;
        g_delay_sender[g_delay_count] = sender_slot_id;
    }
    pthread_mutex_unlock(&g_mutex_delay);

    printf("[SYNC] Delay registado: sender=%u  delay=%.1f ms\n",
           sender_slot_id, delay_ms);
}

/* ─────────────────────────────────────────────────────────────
 * compute_mean()
 * ───────────────────────────────────────────────────────────── */
static float compute_mean(float *arr, int n) {
    if (n == 0) return 0.0f;
    float sum = 0;
    for (int i = 0; i < n; i++) sum += arr[i];
    return sum / n;
}

/* ─────────────────────────────────────────────────────────────
 * shiftSlot()
 * ───────────────────────────────────────────────────────────── */
static void shift_slot(slot_limits_t *s, int32_t delta_ms,
                        uint16_t round_period_ms, uint16_t width_ms)
{
    s->begin_ms = (uint16_t)((s->begin_ms + delta_ms + round_period_ms)
                              % round_period_ms);
    s->end_ms   = (uint16_t)((s->begin_ms + width_ms - GUARD_INTERVAL_MS)
                              % round_period_ms);
}

/* ─────────────────────────────────────────────────────────────
 * sync_adjust_slot()
 *
 * Chamado pelo TX no fim de cada round.
 * Calcula o delta e ajusta o slot.
 * ───────────────────────────────────────────────────────────── */
void sync_adjust_slot(uint16_t round_period_ms) {
    pthread_mutex_lock(&g_mutex_delay);
    int count = g_delay_count;
    float tmp_array[PKTDELAY_ARRAY_SIZE + 1];
    uint8_t tmp_sender[PKTDELAY_ARRAY_SIZE + 1];
    memcpy(tmp_array,  (void*)(g_delay_array  + 1), sizeof(float)   * count);
    memcpy(tmp_sender, (void*)(g_delay_sender + 1), sizeof(uint8_t) * count);
    g_delay_count = 0;  /* limpa para o próximo round */
    pthread_mutex_unlock(&g_mutex_delay);

    if (count == 0) return;

    uint16_t width_ms = round_period_ms / g_num_nodes;

    /* agrupa delays por nó emissor e calcula média por nó */
    float   agg[MAX_NODES]     = {0};
    float   buf[MAX_NODES][PKTDELAY_ARRAY_SIZE] = {{0}};
    int     buf_count[MAX_NODES] = {0};
    uint8_t is_sender[MAX_NODES] = {0};

    for (int i = 0; i < count; i++) {
        uint8_t s = tmp_sender[i];
        if (s == 0 || s > MAX_NODES) continue;
        buf[s-1][buf_count[s-1]++] = tmp_array[i];
        is_sender[s-1] = 1;
    }

    for (int i = 0; i < MAX_NODES; i++) {
        if (!is_sender[i]) continue;
        agg[i] = compute_mean(buf[i], buf_count[i]);
    }

    /* delta = máximo das médias por nó */
    int32_t delta = 0;
    for (int i = 0; i < MAX_NODES; i++) {
        if (!is_sender[i]) continue;
        if ((int32_t)agg[i] > delta)
            delta = (int32_t)agg[i];
    }

    /* limita o movimento a CSI% da largura do slot */
    int32_t lim = (int32_t)(SYNC_CSI * width_ms);
    if (lim < 1) lim = 1;
    if (delta >  lim) delta =  lim;
    if (delta <    0) delta =  0;

    /* aleatoriedade para evitar oscilações (como o Diogo) */
    float rnd = (rand() % 101) * 0.01f;
    delta = (int32_t)(delta * (0.8f + 0.2f * rnd));

    if (delta == 0) return;

    pthread_mutex_lock(&g_mutex_slot);
    shift_slot(&g_slot, delta, round_period_ms, width_ms);
    pthread_mutex_unlock(&g_mutex_slot);

    printf("[SYNC] Slot ajustado: delta=%d ms → [%u, %u] ms\n",
           delta, g_slot.begin_ms, g_slot.end_ms);
}

/* ─────────────────────────────────────────────────────────────
 * sync_slot_begin_us() / sync_slot_end_us()
 *
 * Converte os limites do slot (ms no frame) para timestamps
 * absolutos em microsegundos.
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
    uint64_t round_us   = (uint64_t)round_period_ms * 1000;
    uint16_t t_ms       = (uint16_t)((now_us % round_us) / 1000);
    slot_limits_t s     = sync_get_slot();

    if (s.begin_ms <= s.end_ms)
        return (t_ms >= s.begin_ms && t_ms < s.end_ms);
    else
        return (t_ms >= s.begin_ms || t_ms < s.end_ms);
}
