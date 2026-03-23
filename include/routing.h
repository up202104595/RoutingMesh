/*
 * ═══════════════════════════════════════════════════════════════
 * routing.h - Routing Manager com Link Quality (MST-based)
 *
 * Método: Como Ana Morais (linked lists da MST, SEM BFS!)
 * Contribuição Miguel: Link Quality (0-100) + sync kernel
 * ═══════════════════════════════════════════════════════════════
 */

#ifndef ROUTING_H
#define ROUTING_H

#include <stdint.h>
#include <stdbool.h>
#include <pthread.h>
#include "ip_route_netlink.h"   /* ip_route_add(), ip_forward_enable() */

#define MAX_NODES 20

/* Endereçamento da rede mesh — ajustar conforme hardware real */
#define MESH_NET_BASE  "10.0.0"   /* nó X tem IP 10.0.0.X        */

// ═══════════════════════════════════════════════════════════════
// ESTRUTURAS
// ═══════════════════════════════════════════════════════════════

typedef struct {
    uint32_t packets_received;
    uint32_t packets_expected;
    uint32_t consecutive_losses;
    double   last_seen;
} link_stats_t;

typedef struct routing_entry {
    uint8_t destination;   /* Node ID destino  */
    uint8_t next_hop;      /* Próximo salto    */
    uint8_t hops;          /* Número de hops   */
    uint8_t quality;       /* Qualidade 0-100  */
    bool    valid;         /* Rota válida?     */
} routing_entry_t;

typedef struct routing_manager {
    uint8_t my_node_id;
    uint8_t num_nodes;
    char    mesh_iface[16];   /* "tun<node_id>", e.g. "tun1" */

    routing_entry_t routing_table[MAX_NODES];
    link_stats_t    link_stats[MAX_NODES];

    volatile bool needs_recompute;
    uint32_t      recompute_count;
    uint64_t      last_recompute_time_us;

    pthread_mutex_t lock;
} routing_manager_t;

// ═══════════════════════════════════════════════════════════════
// API PÚBLICA
// ═══════════════════════════════════════════════════════════════

/* Lifecycle */
routing_manager_t* routing_manager_create(uint8_t my_node_id, uint8_t num_nodes);
void routing_manager_destroy(routing_manager_t *rm);

/* Atualizar estatísticas de link */
void routing_manager_update_link_stats(routing_manager_t *rm,
                                       uint8_t node_id,
                                       bool received);

/*
 * Recalcular rotas — chamado pelo Event Handler quando topologia muda.
 *
 * Numa só chamada:
 *   1. Constrói linked lists da MST (método Ana Morais)
 *   2. lookup_next_hop() para cada destino activo
 *   3. Preenche routing_table[i] com {dest, next_hop, quality}
 *   4. ip_route_add("10.0.0.<dest>", "10.0.0.<nh>", MESH_IFACE)
 *      via Netlink RTM_NEWROUTE — sem fork, ~50µs por rota
 *
 * Requer ip_forward=1 (activar em node_init com ip_forward_enable()).
 */
void routing_manager_recompute(routing_manager_t *rm,
                               uint8_t **spanning_tree,
                               uint8_t   link_quality[MAX_NODES][MAX_NODES],
                               uint8_t  *active_nodes,
                               uint8_t   num_active);

/* Lookup de rota (usado pelo Thread TX para unicast) */
uint8_t routing_manager_lookup(routing_manager_t *rm, uint8_t destination);

/* Print routing table */
void routing_manager_print(routing_manager_t *rm);

/* Sinalizar necessidade de recomputação */
void routing_manager_mark_dirty(routing_manager_t *rm);

#endif /* ROUTING_H */