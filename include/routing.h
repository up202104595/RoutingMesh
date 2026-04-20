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
#include "ip_route_netlink.h"

#define MAX_NODES 20

/* Endereçamento da rede mesh TUN */
#define MESH_NET_BASE  "10.0.0"

/* Prefixo da rede física — sobreposto em compilação com -DMESH_NET_PREFIX */
#ifndef MESH_NET_PREFIX
#define MESH_NET_PREFIX "172.20.10"
#endif

/* Interface física — sobreposta em compilação com -DMESH_PHY_IFACE */
#ifndef MESH_PHY_IFACE
#define MESH_PHY_IFACE "wlan0"
#endif

typedef struct {
    uint32_t packets_received;
    uint32_t packets_expected;
    uint32_t consecutive_losses;
    double   last_seen;
} link_stats_t;

typedef struct routing_entry {
    uint8_t destination;
    uint8_t next_hop;
    uint8_t hops;
    uint8_t quality;
    bool    valid;
} routing_entry_t;

typedef struct routing_manager {
    uint8_t my_node_id;
    uint8_t num_nodes;
    char    mesh_iface[16];

    routing_entry_t routing_table[MAX_NODES];
    link_stats_t    link_stats[MAX_NODES];

    volatile bool needs_recompute;
    uint32_t      recompute_count;
    uint64_t      last_recompute_time_us;

    pthread_mutex_t lock;
} routing_manager_t;

routing_manager_t* routing_manager_create(uint8_t my_node_id, uint8_t num_nodes);
void routing_manager_destroy(routing_manager_t *rm);
void routing_manager_update_link_stats(routing_manager_t *rm, uint8_t node_id, bool received);
void routing_manager_recompute(routing_manager_t *rm,
                               uint8_t **spanning_tree,
                               uint8_t   link_quality[MAX_NODES][MAX_NODES],
                               uint8_t  *active_nodes,
                               uint8_t   num_active);
uint8_t routing_manager_lookup(routing_manager_t *rm, uint8_t destination);
void routing_manager_print(routing_manager_t *rm);
void routing_manager_mark_dirty(routing_manager_t *rm);

#endif /* ROUTING_H */
