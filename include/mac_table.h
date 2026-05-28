/*
 * mac_table.h — Tabela de MACs fisicos por node_id
 *
 * Usado pelo metodo ARP (RELAY_METHOD=arp) para associar
 * IP virtual ao MAC fisico do next_hop.
 *
 * Populada pelo Thread RX quando recebe MATRIX de um no.
 * Consultada pelo routing_manager quando instala entradas ARP.
 *
 * Miguel Almeida — FEUP 2025
 */

#ifndef MAC_TABLE_H
#define MAC_TABLE_H

#include <stdint.h>

#define MAC_STR_LEN 18  /* "AA:BB:CC:DD:EE:FF\0" */

/* Inicializa a tabela */
void mac_table_init(void);

/*
 * Tenta obter o MAC fisico de um no via "arp -n 172.20.10.X"
 * e guarda na tabela interna.
 * Chamado pelo Thread RX quando recebe MATRIX de sender_id.
 */
void mac_table_update(uint8_t node_id);

/*
 * Devolve o MAC fisico de um no.
 * Devolve NULL se nao conhecido ainda.
 */
const char* mac_table_get(uint8_t node_id);

/* Print de debug */
void mac_table_print(void);

#endif /* MAC_TABLE_H */