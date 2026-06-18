/*
 * ═══════════════════════════════════════════════════════════════
 * mac_table.h — Tabela MAC ↔ node ID (método Ana Morais)
 *
 * Réplica fiel da macArraySHM_t / macInfo_t da tese (Code Block 3.2).
 *
 * "It was decided to include the MAC address in each node's status
 *  share. Now, each node transmits its MAC address as part of its
 *  state within the synchronization packet." (tese 3.2.3)
 *
 * Cada nó mantém uma tabela id → MAC dos vizinhos directos,
 * populada a partir do trailer de 6 bytes do state packet (MATRIX).
 * O MAC só é retido enquanto a ligação existir.
 * ═══════════════════════════════════════════════════════════════
 */

#ifndef MAC_TABLE_H
#define MAC_TABLE_H

#include <stdint.h>
#include <stddef.h>

#define MAC_BYTES   6
#define MAC_STR_LEN 18  /* "AA:BB:CC:DD:EE:FF\0" */

/* macInfo_t — equivalente à struct da tese (Code Block 3.2) */
typedef struct {
    uint8_t id;                  /* último octeto do IP = node ID */
    uint8_t mac_bytes[MAC_BYTES];
    int     valid;
} macInfo_t;

/* Inicializa a tabela (uma vez no arranque). */
void mac_table_init(void);

/* Lê o MAC físico da interface local (ex.: "wlan0") para out[6].
 * Devolve 0 em sucesso. Usado para preencher o trailer do state packet. */
int mac_table_local_mac(const char *iface, uint8_t out[MAC_BYTES]);

/* Regista/actualiza o MAC de um nó (a partir do state packet recebido). */
void mac_table_set(uint8_t node_id, const uint8_t mac_bytes[MAC_BYTES]);

/* Remove o MAC de um nó (quando a ligação é removida — tese 3.2.3). */
void mac_table_del(uint8_t node_id);

/* Devolve o MAC em bytes. Devolve 0 em sucesso, -1 se desconhecido. */
int mac_table_get_bytes(uint8_t node_id, uint8_t out[MAC_BYTES]);

/* Devolve o MAC como string "AA:BB:CC:DD:EE:FF" ou NULL se desconhecido. */
const char* mac_table_get_str(uint8_t node_id);

void mac_table_print(void);

#endif /* MAC_TABLE_H */
