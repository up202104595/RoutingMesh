/*
 * pdr.h  —  Packet Delivery Ratio
 *
 * Baseado no modulo PDR de Diogo Almeida (2023).
 * Adaptado para usar msg_id do MSG_DATA em vez de seq_num TDMA.
 *
 * Calcula PDR do link other_node -> este_no com base nos
 * msg_id recebidos. Actualiza MATRIX_setLinkQuality() directamente.
 *
 * Miguel Almeida — FEUP 2025
 */

#ifndef PDR_H
#define PDR_H

#include <stdint.h>

#define PDR_SEQ_TABLE_SIZE  300   /* ultimos N msg_ids guardados por no */
#define PDR_UPDATE_INTERVAL  10   /* actualiza link_quality a cada N pacotes */

/* Inicializa estruturas PDR */
void pdr_init(void);

/*
 * Chamado pelo Thread RX quando recebe MSG_DATA.
 * Regista msg_id e actualiza estimativa de PDR.
 * Se PDR actualizado: chama MATRIX_setLinkQuality(src_id, pdr_quality).
 */
void pdr_update(uint8_t src_id, uint16_t msg_id);

/* Devolve PDR estimado (0-100) para o link src_id -> este_no */
float pdr_get(uint8_t src_id);

/* Print de debug */
void pdr_print(uint8_t src_id);

#endif /* PDR_H */