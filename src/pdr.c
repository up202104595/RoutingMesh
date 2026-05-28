/*
 * pdr.c  —  Packet Delivery Ratio
 *
 * Baseado no modulo PDR de Diogo Almeida (2023).
 * Adaptado para MSG_DATA msg_id em vez de seq_num TDMA.
 *
 * Algoritmo (identico ao Diogo):
 *   1. Guarda ultimos PDR_SEQ_TABLE_SIZE msg_ids por src_id
 *   2. missed = soma dos gaps entre msg_ids consecutivos
 *   3. PDR = 100 * (range - missed) / range
 *   4. Chama MATRIX_setLinkQuality(src_id, PDR) a cada PDR_UPDATE_INTERVAL pacotes
 *
 * Miguel Almeida — FEUP 2025
 */

#include "pdr.h"
#include "matrix.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

/* tabela de seq_nums por no — como no Diogo */
static uint32_t g_seq_table[MAX_NODES + 1][PDR_SEQ_TABLE_SIZE];
static uint16_t g_seq_w_ptr[MAX_NODES + 1];
static float    g_pdr_in[MAX_NODES + 1];       /* PDR link src->eu */
static uint16_t g_pkt_count[MAX_NODES + 1];    /* contador de pacotes por no */

/* ─────────────────────────────────────────────────────────────
 * pdr_init()
 * ───────────────────────────────────────────────────────────── */
void pdr_init(void) {
    memset(g_seq_table,  0, sizeof(g_seq_table));
    memset(g_seq_w_ptr,  0, sizeof(g_seq_w_ptr));
    memset(g_pkt_count,  0, sizeof(g_pkt_count));
    for (int i = 0; i <= MAX_NODES; i++)
        g_pdr_in[i] = -1.0f;  /* -1 = sem estimativa ainda */
    printf("[PDR] Inicializado\n");
}

/* ─────────────────────────────────────────────────────────────
 * pdr_estimate()
 *
 * Portado directamente de PDR_estimate() do Diogo.
 * ───────────────────────────────────────────────────────────── */
static void pdr_estimate(uint8_t src_id, uint32_t seq_num) {
    if (src_id == 0 || src_id > MAX_NODES) return;

    /* guarda seq_num na tabela circular */
    g_seq_table[src_id][g_seq_w_ptr[src_id]] = seq_num;
    g_seq_w_ptr[src_id] = (g_seq_w_ptr[src_id] + 1) % PDR_SEQ_TABLE_SIZE;

    /* calcula missed e range — como no Diogo */
    uint32_t missed = 0;
    uint32_t min_seq = seq_num, max_seq = seq_num;

    for (int i = 0; i < PDR_SEQ_TABLE_SIZE - 1; i++) {
        int cur  = i % PDR_SEQ_TABLE_SIZE;
        if (g_seq_table[src_id][cur] == 0) continue;

        int next = (i + 1) % PDR_SEQ_TABLE_SIZE;
        if (g_seq_table[src_id][next] == 0) continue;

        int64_t diff = (int64_t)g_seq_table[src_id][next] -
                       (int64_t)g_seq_table[src_id][cur] - 1;
        if (diff > 0)
            missed += (uint32_t)diff;

        if (g_seq_table[src_id][cur] < min_seq)
            min_seq = g_seq_table[src_id][cur];

        /* seq_num fora de ordem — reset tabela (como no Diogo) */
        if (g_seq_table[src_id][cur] > seq_num) {
            printf("[PDR] Node %u: seq_num fora de ordem — reset tabela\n", src_id);
            memset(g_seq_table[src_id], 0,
                   PDR_SEQ_TABLE_SIZE * sizeof(uint32_t));
            return;
        }
    }

    float range = (float)(max_seq - min_seq);
    if (range <= 0) return;  /* poucos dados ainda */

    g_pdr_in[src_id] = 100.0f * (range - (float)missed) / range;

    /* limita a [0, 100] */
    if (g_pdr_in[src_id] < 0)   g_pdr_in[src_id] = 0;
    if (g_pdr_in[src_id] > 100) g_pdr_in[src_id] = 100;
}

/* ─────────────────────────────────────────────────────────────
 * pdr_update()
 *
 * Chamado pelo Thread RX quando recebe MSG_DATA.
 * ───────────────────────────────────────────────────────────── */
void pdr_update(uint8_t src_id, uint16_t msg_id) {
    if (src_id == 0 || src_id > MAX_NODES) return;

    g_pkt_count[src_id]++;

    pdr_estimate(src_id, (uint32_t)msg_id);

    /* actualiza link_quality a cada PDR_UPDATE_INTERVAL pacotes */
    if (g_pkt_count[src_id] % PDR_UPDATE_INTERVAL == 0) {
        if (g_pdr_in[src_id] >= 0) {
            uint8_t quality = (uint8_t)g_pdr_in[src_id];
            MATRIX_setLinkQuality(src_id, quality);
            printf("[PDR] Node %u → PDR=%.1f%%  quality=%u\n",
                   src_id, g_pdr_in[src_id], quality);
        }
    }
}

/* ─────────────────────────────────────────────────────────────
 * pdr_get()
 * ───────────────────────────────────────────────────────────── */
float pdr_get(uint8_t src_id) {
    if (src_id == 0 || src_id > MAX_NODES) return -1.0f;
    return g_pdr_in[src_id];
}

/* ─────────────────────────────────────────────────────────────
 * pdr_print()
 * ───────────────────────────────────────────────────────────── */
void pdr_print(uint8_t src_id) {
    printf("[PDR] Link Node%u → meu: PDR=%.2f%%\n",
           src_id, g_pdr_in[src_id]);
}