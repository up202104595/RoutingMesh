/*
 * ═══════════════════════════════════════════════════════════════
 * routing_list.h — Routing matrix como linked list (método Ana)
 *
 * Réplica fiel da routingList_t da tese (Code Block 3.3) e do
 * algoritmo de update incremental por DFS + qsort (Secção 3.2.4).
 *
 *   typedef struct routingList_ {
 *       uint8_t id;
 *       uint8_t macAddress[MAC_BYTES];
 *       struct routingList_* next;             // lista primária
 *       struct routingList_* accessibleNodes;  // lista secundária
 *   } routingList_t;
 *
 * Lista primária  = vizinhos com ligação directa ao nó local.
 * Lista secundária= nós alcançáveis através de cada vizinho directo.
 *
 * As rotas são instaladas na tabela ARP do kernel via ioctl()
 * (SIOCSARP), associando o IP virtual do destino ao MAC do
 * vizinho directo (next-hop). Tese: "far faster and more suitable
 * for real-time network environments than popen() or system()".
 * ═══════════════════════════════════════════════════════════════
 */

#ifndef ROUTING_LIST_H
#define ROUTING_LIST_H

#include <stdint.h>
#include <pthread.h>
#include "mac_table.h"

#define RL_MAX_NODES 20

typedef struct routingList_ {
    uint8_t id;
    uint8_t macAddress[MAC_BYTES];
    struct routingList_ *next;            /* próximo vizinho directo */
    struct routingList_ *accessibleNodes; /* nós alcançáveis via este */
} routingList_t;

typedef struct {
    uint8_t  my_node_id;
    char     mesh_prefix[24];   /* IP virtual dos destinos, ex. "10.0.0" */
    char     phy_iface[16];     /* interface física p/ ARP, ex. "wlan0"  */

    routingList_t *primary;     /* cabeça da lista primária */

    /* cache plana para lookup O(1) do next-hop pelo framework */
    uint8_t  next_hop[RL_MAX_NODES + 1];

    /* grupo de IDs activos do ciclo anterior (detecção de saídas) */
    uint8_t  prev_active[RL_MAX_NODES];
    uint8_t  prev_num_active;

    uint32_t update_count;
    uint64_t last_update_us;
    pthread_mutex_t lock;
} routing_ctx_t;

routing_ctx_t* routing_create(uint8_t my_node_id,
                              const char *mesh_prefix,
                              const char *phy_iface);
void routing_destroy(routing_ctx_t *ctx);

/* Recalcula a routing matrix a partir da MST (spanning tree).
 * spanning_tree[i][j] = 1 se há aresta MST entre índices i e j.
 * active_nodes[] mapeia índice → node ID. */
void routing_update(routing_ctx_t *ctx,
                    uint8_t **spanning_tree,
                    uint8_t  *active_nodes,
                    uint8_t   num_active);

/* Next-hop (ID do vizinho directo) para um destino, ou 0 se sem rota. */
uint8_t routing_next_hop(routing_ctx_t *ctx, uint8_t dest_id);

void routing_print(routing_ctx_t *ctx);

#endif /* ROUTING_LIST_H */
