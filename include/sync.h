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
 * BANDA MORTA + GATE DE CONVERGÊNCIA
 *
 * Banda morta: o algoritmo do Diogo é forward-only (só avança o slot). Há um
 * resíduo sistemático de ~3 ms (tempo entre o slot ideal do vizinho e o
 * instante em que processamos o beacon) que, sozinho, empurra o slot para a
 * frente todas as rondas — rotação perpétua. Como cada nó avança um valor
 * ligeiramente diferente (truncatura + componente aleatória), os slots
 * afastam-se até passarem o guard e colidirem. A banda morta pára de corrigir
 * quando o desalinhamento já está dentro do guard: o slot estabiliza.
 *
 * Gate: o tráfego de DADOS (vídeo) só é admitido depois de a sincronização ter
 * convergido (SYNC_STABLE_ROUNDS rondas seguidas dentro da banda morta), ou ao
 * fim de um tecto rígido (SYNC_CONVERGE_CAP_MS) para nunca esperar de mais.
 * Os beacons MATRIX continuam sempre a ser enviados (são precisos para o sync).
 */
#define SYNC_DEADBAND_MS       4      /* não corrigir desalinhamentos <= isto (guard=5 ms) */
#define SYNC_STABLE_ROUNDS     8      /* rondas seguidas dentro da banda morta = convergido */
#define SYNC_CONVERGE_CAP_MS   90000  /* tecto: admite dados ao fim de 90 s mesmo sem convergir */

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

/* ── Convergência da sincronização ──
 * sync_is_stable(): true após SYNC_STABLE_ROUNDS rondas seguidas dentro da
 *                   banda morta (o slot deixou de precisar de correção).
 * sync_data_plane_ready(): true quando se pode admitir tráfego de dados —
 *                   convergido OU passado o tecto rígido (SYNC_CONVERGE_CAP_MS). */
int sync_is_stable(void);
int sync_data_plane_ready(void);

#endif /* SYNC_H */