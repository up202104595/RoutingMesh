/*
 * ═══════════════════════════════════════════════════════════════
 * routing.c - Routing baseado em MST (MÉTODO DA ANA MORAIS!)
 *
 * Método: Linked Lists diretamente da MST (SEM BFS!)
 * Contribuição Miguel: Link Quality (0-100) + ip_route_sync kernel
 * ═══════════════════════════════════════════════════════════════
 */

#include "routing.h"
#include "matrix.h"
#include "tun.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>

typedef struct route_node {
    uint8_t node_id;
    uint8_t quality;
    struct route_node *reachable;
    struct route_node *next;
} route_node_t;

static uint64_t get_time_us(void) {
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return (uint64_t)tv.tv_sec * 1000000 + tv.tv_usec;
}

static double getEpoch(void) {
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return tv.tv_sec + tv.tv_usec / 1000000.0;
}

static int8_t find_node_index(uint8_t *active_nodes, uint8_t num_active, uint8_t node_id) {
    for (int i = 0; i < num_active; i++)
        if (active_nodes[i] == node_id) return i;
    return -1;
}

static bool is_reachable_via_mst(uint8_t **mst, uint8_t num_active,
                                  uint8_t start_idx, uint8_t target_idx,
                                  bool *visited) {
    if (start_idx == target_idx) return true;
    visited[start_idx] = true;
    for (int i = 0; i < num_active; i++)
        if (mst[start_idx][i] && !visited[i])
            if (is_reachable_via_mst(mst, num_active, i, target_idx, visited))
                return true;
    return false;
}

static void free_routing_lists(route_node_t *list) {
    while (list) {
        route_node_t *next_primary = list->next;
        route_node_t *secondary    = list->reachable;
        while (secondary) {
            route_node_t *next_sec = secondary->next;
            free(secondary);
            secondary = next_sec;
        }
        free(list);
        list = next_primary;
    }
}

static route_node_t* build_routing_structure(
    uint8_t  my_node_id,
    uint8_t **mst,
    uint8_t   link_quality[MAX_NODES][MAX_NODES],
    uint8_t  *active_nodes,
    uint8_t   num_active)
{
    route_node_t *primary_list = NULL;
    int8_t my_idx = find_node_index(active_nodes, num_active, my_node_id);
    if (my_idx == -1) return NULL;

    printf("[ROUTING] Construindo estrutura de routing...\n");

    for (int i = 0; i < num_active; i++) {
        if (mst[my_idx][i] != 1) continue;

        uint8_t neighbor_id = active_nodes[i];
        uint8_t quality     = link_quality[my_idx][i];

        printf("[ROUTING]   Vizinho direto: Node %d (quality: %d)\n", neighbor_id, quality);

        route_node_t *primary = malloc(sizeof(route_node_t));
        primary->node_id   = neighbor_id;
        primary->quality   = quality;
        primary->reachable = NULL;
        primary->next      = primary_list;
        primary_list       = primary;

        for (int j = 0; j < num_active; j++) {
            if (j == my_idx || j == i) continue;

            bool visited[MAX_NODES] = {false};
            visited[my_idx] = true;

            if (is_reachable_via_mst(mst, num_active, i, j, visited)) {
                route_node_t *secondary = malloc(sizeof(route_node_t));
                secondary->node_id  = active_nodes[j];
                secondary->quality  = 0;
                secondary->next     = primary->reachable;
                primary->reachable  = secondary;

                printf("[ROUTING]     -> Alcancavel via Node %d: Node %d\n",
                       neighbor_id, active_nodes[j]);
            }
        }
    }
    return primary_list;
}

static uint8_t lookup_next_hop(route_node_t *primary_list, uint8_t destination) {
    for (route_node_t *p = primary_list; p != NULL; p = p->next)
        for (route_node_t *s = p->reachable; s != NULL; s = s->next)
            if (s->node_id == destination)
                return p->node_id;

    for (route_node_t *p = primary_list; p != NULL; p = p->next)
        if (p->node_id == destination)
            return p->node_id;

    return 0;
}

/*
 * Instala a ip rule para tráfego de relay vindo do wlan0.
 *
 * Cenário 2+ relays:
 *   N1 → TCP → N2 → ip_forward → wlan0 → N3
 *   N3 recebe pelo wlan0, precisa de relay para N4:
 *     iif wlan0 → tabela 200 → ip_forward → wlan0 → N4
 *
 * A regra iif tun (instalada em tun_open) cobre o primeiro hop de relay.
 * Esta regra cobre hops subsequentes onde o pacote chega pelo wlan0.
 *
 * Nota: priority 99 < priority 100 (tun rule) garante que wlan0 é
 * avaliado primeiro, evitando conflito com tráfego local.
 */
static void install_wlan_relay_rule(const char *phy_iface) {
    char cmd[256];

    /* Remove regra anterior se existir (idempotente) */
    snprintf(cmd, sizeof(cmd),
             "ip rule del iif %s lookup 200 priority 99 2>/dev/null || true",
             phy_iface);
    system(cmd);

    /* Instala regra: tráfego recebido pelo wlan0 → tabela 200 */
    snprintf(cmd, sizeof(cmd),
             "ip rule add iif %s lookup 200 priority 99",
             phy_iface);
    if (system(cmd) != 0) {
        fprintf(stderr, "[ROUTING] AVISO: falha ao instalar ip rule iif %s lookup 200\n",
                phy_iface);
    } else {
        printf("[ROUTING] ip rule add iif %s lookup 200 priority 99 [OK]\n", phy_iface);
    }
}

routing_manager_t* routing_manager_create(uint8_t my_node_id, uint8_t num_nodes) {
    routing_manager_t *rm = calloc(1, sizeof(routing_manager_t));
    if (!rm) return NULL;

    rm->my_node_id      = my_node_id;
    rm->num_nodes       = num_nodes;
    rm->needs_recompute = false;
    rm->recompute_count = 0;
    snprintf(rm->mesh_iface, sizeof(rm->mesh_iface), "tun%u", my_node_id);
    pthread_mutex_init(&rm->lock, NULL);

    printf("[ROUTING] Manager criado para Node %d\n", my_node_id);
    return rm;
}

void routing_manager_destroy(routing_manager_t *rm) {
    if (!rm) return;
    pthread_mutex_destroy(&rm->lock);
    free(rm);
}

void routing_manager_update_link_stats(routing_manager_t *rm,
                                       uint8_t node_id, bool received) {
    pthread_mutex_lock(&rm->lock);
    link_stats_t *stats = &rm->link_stats[node_id];
    if (received) {
        stats->packets_received++;
        stats->packets_expected++;
        stats->consecutive_losses = 0;
        stats->last_seen = getEpoch();
    } else {
        stats->packets_expected++;
        stats->consecutive_losses++;
    }
    pthread_mutex_unlock(&rm->lock);
}

void routing_manager_recompute(routing_manager_t *rm,
                               uint8_t **spanning_tree,
                               uint8_t   link_quality[MAX_NODES][MAX_NODES],
                               uint8_t  *active_nodes,
                               uint8_t   num_active) {

    pthread_mutex_lock(&rm->lock);
    uint64_t start = get_time_us();

    printf("\n[ROUTING] =============================================\n");
    printf("[ROUTING] Recalculando rotas (Metodo Ana + Link Quality)\n");
    printf("[ROUTING] =============================================\n");

    /* Remove rotas /32 anteriores antes de recalcular */
    ip_route_flush_mesh(MESH_NET_BASE, rm->num_nodes, rm->mesh_iface);

    /*
     * Garante que a regra de relay via wlan0 está instalada.
     * Necessário para suportar 2+ hops de relay via ip_forward:
     *   pacote chega pelo wlan0 → tabela 200 → ip_forward → wlan0 → próximo hop
     */
    install_wlan_relay_rule(MESH_PHY_IFACE);

    route_node_t *primary_list = build_routing_structure(
        rm->my_node_id, spanning_tree, link_quality, active_nodes, num_active);

    memset(rm->routing_table, 0, sizeof(rm->routing_table));
    int8_t my_idx = find_node_index(active_nodes, num_active, rm->my_node_id);

    for (int i = 0; i < num_active; i++) {
        uint8_t dest_id = active_nodes[i];

        if (dest_id == rm->my_node_id) {
            rm->routing_table[i].valid = false;
            continue;
        }

        uint8_t next_hop = lookup_next_hop(primary_list, dest_id);
        if (next_hop == 0) continue;

        rm->routing_table[i].destination = dest_id;
        rm->routing_table[i].next_hop    = next_hop;
        rm->routing_table[i].valid       = true;

        int8_t nh_idx = find_node_index(active_nodes, num_active, next_hop);
        if (my_idx != -1 && nh_idx != -1)
            rm->routing_table[i].quality = link_quality[my_idx][nh_idx];

        /* Rotas /32 no kernel — política dupla:
         *
         * Tabela MAIN (src = próprio nó):
         *   10.0.0.X via 10.0.0.nhop dev tunY
         *   → tun_reader interceta e envia via TCP na slot TDMA
         *
         * Tabela 200 (relay via wlan0, 1º hop):
         *   10.0.0.X via 172.20.10.nhop dev wlan0
         *   → ip rule iif tunY lookup 200  (instalado em tun_open)
         *   → kernel faz ip_forward direto para wlan0
         *
         * Tabela 200 (relay via wlan0, 2º+ hop):
         *   mesmas rotas da tabela 200
         *   → ip rule iif wlan0 lookup 200  (instalado aqui, priority 99)
         *   → kernel faz ip_forward para o próximo hop via wlan0
         */
        {
            char dest_ip[32], tun_gw[32], phy_gw[32];
            snprintf(dest_ip, sizeof(dest_ip), "%s.%u", MESH_NET_BASE,   dest_id);
            snprintf(tun_gw,  sizeof(tun_gw),  "%s.%u", MESH_NET_BASE,   next_hop);
            snprintf(phy_gw,  sizeof(phy_gw),  "%s.%u", MESH_NET_PREFIX, next_hop);

            /* tabela main: trafego proprio via TUN → TDMA */
            ip_route_add(dest_ip, tun_gw, rm->mesh_iface);

            /* tabela 200: relay via wlan0 → ip_forward direto (1º e 2º+ hop) */
            ip_route_add_t(dest_ip, phy_gw, MESH_PHY_IFACE, 200);

            if (dest_id == next_hop)
                printf("[ROUTING]   %s via %s dev %s (main) + via %s dev %s (t200) [directo]\n",
                       dest_ip, tun_gw, rm->mesh_iface, phy_gw, MESH_PHY_IFACE);
            else
                printf("[ROUTING]   %s via %s dev %s (main) + via %s dev %s (t200) [relay via %d]\n",
                       dest_ip, tun_gw, rm->mesh_iface, phy_gw, MESH_PHY_IFACE, next_hop);
        }
    }

    free_routing_lists(primary_list);

    uint64_t elapsed           = get_time_us() - start;
    rm->last_recompute_time_us = elapsed;
    rm->recompute_count++;
    rm->needs_recompute = false;

    printf("[ROUTING] Rotas recalculadas em %lu us\n", elapsed);
    printf("[ROUTING] =============================================\n\n");

    pthread_mutex_unlock(&rm->lock);
}

uint8_t routing_manager_lookup(routing_manager_t *rm, uint8_t destination) {
    pthread_mutex_lock(&rm->lock);
    uint8_t next_hop = 0;
    for (int i = 0; i < rm->num_nodes; i++) {
        if (rm->routing_table[i].destination == destination &&
            rm->routing_table[i].valid) {
            next_hop = rm->routing_table[i].next_hop;
            break;
        }
    }
    pthread_mutex_unlock(&rm->lock);
    return next_hop;
}

void routing_manager_print(routing_manager_t *rm) {
    pthread_mutex_lock(&rm->lock);

    printf("\n+------------------------------------------------+\n");
    printf("|  ROUTING TABLE - Node %d                      |\n", rm->my_node_id);
    printf("+--------+----------+---------+------------------+\n");
    printf("| Dest   | Next Hop | Quality | Valid            |\n");
    printf("+--------+----------+---------+------------------+\n");

    bool has_routes = false;
    for (int i = 0; i < MAX_NODES; i++) {
        if (rm->routing_table[i].valid) {
            printf("|  %2d    |    %2d    |   %3d   |    OK          |\n",
                   rm->routing_table[i].destination,
                   rm->routing_table[i].next_hop,
                   rm->routing_table[i].quality);
            has_routes = true;
        }
    }

    if (!has_routes)
        printf("|             (sem rotas)                      |\n");

    printf("+------------------------------------------------+\n\n");
    pthread_mutex_unlock(&rm->lock);
}

void routing_manager_mark_dirty(routing_manager_t *rm) {
    rm->needs_recompute = true;
}
