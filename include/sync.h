/*
 * ═══════════════════════════════════════════════════════════════
 * sync.h  —  Sincronização relativa de slots TDMA
 *
 * Baseado no algoritmo do Diogo Almeida (2023).
 * Cada nó ajusta dinamicamente os limites do seu slot
 * com base nos delays dos pacotes recebidos.
 *
 * Algoritmo:
 *   1. Por cada pacote MATRIX recebido → sync_record_delay()
 *   2. No fim de cada round → sync_compute_delta() → sync_shift_slot()
 *   3. O slot move-se no máximo CSI% da sua largura por round
 * ═══════════════════════════════════════════════════════════════
 */

#ifndef SYNC_H
#define SYNC_H

#include <stdint.h>

#define PKTDELAY_ARRAY_SIZE  64    /* máx delays guardados por round */
#define SYNC_CSI             0.10  /* máx movimento por round: 10% da largura do slot */
#define GUARD_INTERVAL_MS    2     /* margem de guarda no fim do slot (ms) */

/*
 * SOLUCAO A — ANCORA A POSICAO NOMINAL
 *
 * O algoritmo do Diogo e forward-only e tem um equilibrio degenerado: quando os
 * slots colapsam uns sobre os outros, cada no mede delay ~0 (acha-se alinhado,
 * porque mede posicao RELATIVA aos vizinhos, e eles estao todos no mesmo sitio)
 * e deixa de corrigir -> ficam colados -> colisoes. A ancora adiciona uma forca
 * que puxa o slot de volta a sua posicao nominal atribuida (N1->0, N2->50,
 * N3->100 num frame de 150ms), quebrando esse equilibrio. A correcao relativa
 * continua a alinhar com os vizinhos (imune a deriva de relogio); a ancora so
 * impede o colapso, garantindo os ~50ms de espacamento.
 *
 * Ganho: fracao da distancia ao nominal corrigida por ronda. Afinavel em campo.
 */
#define SYNC_ANCHOR_GAIN     0.25

/*
 * Limites do slot (em ms dentro do frame/round)
 */
typedef struct {
    uint16_t begin_ms;
    uint16_t end_ms;
} slot_limits_t;

/* ── Lifecycle ── */
void sync_init(uint8_t slot_id, uint8_t num_nodes, uint16_t round_period_ms);

/* ── Chamado pelo RX para cada pacote MATRIX recebido ── */
void sync_record_delay(uint8_t sender_slot_id,
                       double  rx_timestamp_s,
                       uint16_t sender_begin_ms,
                       uint16_t sender_end_ms,
                       uint16_t round_period_ms);

/* ── Chamado pelo TX no fim de cada round ── */
void sync_adjust_slot(uint16_t round_period_ms);

/* ── Devolve os limites actuais do slot (thread-safe) ── */
slot_limits_t sync_get_slot(void);

/* ── Devolve begin e end em microsegundos absolutos ── */
uint64_t sync_slot_begin_us(uint64_t now_us, uint16_t round_period_ms);
uint64_t sync_slot_end_us(uint64_t now_us, uint16_t round_period_ms);

/* ── Verifica se agora está dentro do slot ── */
int sync_in_slot(uint64_t now_us, uint16_t round_period_ms);

#endif /* SYNC_H */