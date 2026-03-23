/*
 * ═══════════════════════════════════════════════════════════════
 * msg_data.h  —  Payload de dados aplicacionais (MSG_DATA)
 *
 * Encapsula pacotes IP raw lidos da interface TUN (tun0).
 * Transportados sobre TDMA no slot do nó origem.
 *
 * Layout no wire:
 *  [ tdma_header_t ][ msg_data_hdr_t ][ payload: IP packet raw ]
 * ═══════════════════════════════════════════════════════════════
 */

#ifndef MSG_DATA_H
#define MSG_DATA_H

#include <stdint.h>

#define MSG_DATA_MAX_PAYLOAD  1500  /* MTU standard — frame IP completo */

/*
 * src_id   — nó que originou os dados (não o next-hop)
 * dst_id   — nó destino final
 * msg_id   — contador crescente por (src,dst) para medir perdas
 * data_len — tamanho do pacote IP em payload[]
 */
typedef struct __attribute__((packed)) {
    uint8_t  src_id;
    uint8_t  dst_id;
    uint16_t msg_id;
    uint16_t data_len;
    uint8_t  payload[MSG_DATA_MAX_PAYLOAD];
} msg_data_hdr_t;

#endif /* MSG_DATA_H */