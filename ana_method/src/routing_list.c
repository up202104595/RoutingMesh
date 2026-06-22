/*
 * routing_list.c — Routing matrix como linked list (método Ana Morais)
 *
 * Constrói a routing matrix a partir da MST (Prim binário):
 *   - lista primária  = vizinhos directos do nó local
 *   - lista secundária= nós alcançáveis através de cada vizinho (DFS)
 *   - listas secundárias ordenadas por ID via qsort (Secção 3.2.4),
 *     o que permite o diff incremental para só tocar na tabela ARP
 *     quando uma rota muda de facto.
 *
 * As rotas vão para a tabela ARP do kernel via ioctl() (SIOCSARP),
 * via net_ana_arp_set()/net_ana_arp_del() (ioctl SIOCSARP/SIOCDARP).
 *
 * As entradas mapeiam o IP físico do destino -> MAC do next-hop na
 * interface ad-hoc. É o KERNEL que reencaminha (ip_forward), não o
 * framework — exactamente como na tese (3.2 / 4.4).
 */

#include "routing_list.h"
#include "net_ana.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <sys/time.h>

static uint64_t now_us(void) {
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return (uint64_t)tv.tv_sec * 1000000 + tv.tv_usec;
}

static int cmp_u8(const void *a, const void *b) {
    return (int)(*(const uint8_t *)a) - (int)(*(const uint8_t *)b);
}

/* DFS sobre a MST a partir de start_idx, sem atravessar block_idx
 * (o nó local). Recolhe os node IDs alcançáveis (excepto start) em out[]. */
static void dfs_collect(uint8_t **mst, uint8_t num_active,
                        uint8_t *active_nodes,
                        int start_idx, int block_idx,
                        bool *visited, uint8_t *out, int *out_n) {
    visited[start_idx] = true;
    for (int v = 0; v < num_active; v++) {
        if (v == block_idx || visited[v]) continue;
        if (mst[start_idx][v]) {
            out[(*out_n)++] = active_nodes[v];
            dfs_collect(mst, num_active, active_nodes, v, block_idx,
                        visited, out, out_n);
        }
    }
}

static int8_t idx_of(uint8_t *active_nodes, uint8_t num_active, uint8_t id) {
    for (int i = 0; i < num_active; i++)
        if (active_nodes[i] == id) return i;
    return -1;
}

static void free_lists(routingList_t *p) {
    while (p) {
        routingList_t *pn = p->next;
        routingList_t *s = p->accessibleNodes;
        while (s) { routingList_t *sn = s->next; free(s); s = sn; }
        free(p);
        p = pn;
    }
}

routing_ctx_t* routing_create(uint8_t my_node_id,
                              const char *mesh_prefix,
                              const char *phy_iface) {
    routing_ctx_t *ctx = calloc(1, sizeof(*ctx));
    if (!ctx) return NULL;
    ctx->my_node_id = my_node_id;
    snprintf(ctx->mesh_prefix, sizeof(ctx->mesh_prefix), "%s", mesh_prefix);
    snprintf(ctx->phy_iface,   sizeof(ctx->phy_iface),   "%s", phy_iface);
    pthread_mutex_init(&ctx->lock, NULL);
    printf("[ROUTING-ANA] Criado para Node %u (ARP em %s.x, dev=%s)\n",
           my_node_id, mesh_prefix, phy_iface);
    return ctx;
}

void routing_destroy(routing_ctx_t *ctx) {
    if (!ctx) return;
    free_lists(ctx->primary);
    pthread_mutex_destroy(&ctx->lock);
    free(ctx);
}

void routing_update(routing_ctx_t *ctx,
                    uint8_t **mst,
                    uint8_t  *active_nodes,
                    uint8_t   num_active) {
    pthread_mutex_lock(&ctx->lock);
    uint64_t t0 = now_us();

    int8_t my_idx = idx_of(active_nodes, num_active, ctx->my_node_id);
    if (my_idx < 0) { pthread_mutex_unlock(&ctx->lock); return; }

    /* ── 1. Detecção de saídas do grupo de sync → ARP delete ──
     * "We only need to delete a node from the ARP table when the
     *  members of the synchronization group change (when one leaves)." */
    for (int i = 0; i < ctx->prev_num_active; i++) {
        uint8_t old_id = ctx->prev_active[i];
        if (idx_of(active_nodes, num_active, old_id) < 0) {
            char ip[40], rcmd[120];
            snprintf(ip, sizeof(ip), "%s.%u", ctx->mesh_prefix, old_id);
            net_ana_arp_del(ctx->phy_iface, ip);
            snprintf(rcmd, sizeof(rcmd), "ip route del %s/32 2>/dev/null", ip);
            system(rcmd);
            mac_table_del(old_id);
            printf("[ROUTING-ANA] Node %u saiu — arp/route del %s\n", old_id, ip);
        }
    }

    /* ── 2. Reconstrói a linked list a partir da MST ── */
    free_lists(ctx->primary);
    ctx->primary = NULL;

    uint8_t new_next_hop[RL_MAX_NODES + 1];
    memset(new_next_hop, 0, sizeof(new_next_hop));

    for (int i = 0; i < num_active; i++) {
        if (mst[my_idx][i] != 1) continue;       /* só vizinhos directos */

        uint8_t neigh_id = active_nodes[i];
        routingList_t *prim = calloc(1, sizeof(routingList_t));
        prim->id = neigh_id;
        mac_table_get_bytes(neigh_id, prim->macAddress);
        prim->next = ctx->primary;
        ctx->primary = prim;

        new_next_hop[neigh_id] = neigh_id;        /* vizinho directo */

        /* DFS para recolher alcançáveis através deste vizinho */
        bool visited[RL_MAX_NODES] = { false };
        visited[my_idx] = true;
        uint8_t reach[RL_MAX_NODES];
        int rn = 0;
        dfs_collect(mst, num_active, active_nodes, i, my_idx,
                    visited, reach, &rn);

        /* qsort — ordena por ID (permite diff incremental, tese 3.2.4) */
        qsort(reach, rn, sizeof(uint8_t), cmp_u8);

        /* constrói a lista secundária ordenada */
        routingList_t *tail = NULL;
        for (int k = 0; k < rn; k++) {
            if (reach[k] == ctx->my_node_id || reach[k] == neigh_id) continue;
            routingList_t *sec = calloc(1, sizeof(routingList_t));
            sec->id = reach[k];
            memcpy(sec->macAddress, prim->macAddress, MAC_BYTES);
            if (tail) tail->next = sec; else prim->accessibleNodes = sec;
            tail = sec;
            new_next_hop[reach[k]] = neigh_id;    /* alcançável via vizinho */
        }
    }

    /* ── 3. Diff incremental → tabela ARP ──
     * Só instala/actualiza ARP quando o next-hop de um destino muda
     * (entrada nova ou nó que mudou de posição). Evita ARP redundante. */
    int arp_changes = 0;
    for (int dest = 1; dest <= RL_MAX_NODES; dest++) {
        if (dest == ctx->my_node_id) continue;
        uint8_t nh = new_next_hop[dest];
        if (nh == 0) continue;                    /* sem rota */
        if (nh == ctx->next_hop[dest]) continue;  /* inalterado — não toca ARP */

        const char *mac = mac_table_get_str(nh);
        if (!mac) {
            printf("[ROUTING-ANA]   MAC do next-hop %u ainda desconhecido (dest %d)\n",
                   nh, dest);
            continue;
        }
        char ip[40], rcmd[160];
        snprintf(ip, sizeof(ip), "%s.%u", ctx->mesh_prefix, dest);
        net_ana_arp_set(ctx->phy_iface, ip, mac); /* ioctl SIOCSARP */
        /* rota /32 para o kernel reenviar o IP mesh por wlan0 (em vez de o
         * mandar para a tun), com src = IP mesh local -> a DATA sai com
         * origem 10.0.0.<self>, imune ao iptables -s <IP físico>. */
        snprintf(rcmd, sizeof(rcmd),
                 "ip route replace %s/32 dev %s src %s.%u 2>/dev/null",
                 ip, ctx->phy_iface, ctx->mesh_prefix, ctx->my_node_id);
        system(rcmd);
        arp_changes++;
        if (dest == nh)
            printf("[ROUTING-ANA]   arp+route %s -> %s dev %s  [directo]\n",
                   ip, mac, ctx->phy_iface);
        else
            printf("[ROUTING-ANA]   arp+route %s -> %s dev %s  [via %u]\n",
                   ip, mac, ctx->phy_iface, nh);
    }

    memcpy(ctx->next_hop, new_next_hop, sizeof(ctx->next_hop));
    memcpy(ctx->prev_active, active_nodes, num_active);
    ctx->prev_num_active = num_active;

    ctx->update_count++;
    ctx->last_update_us = now_us() - t0;
    pthread_mutex_unlock(&ctx->lock);

    printf("[ROUTING-ANA] Update #%u: %d alteração(ões) ARP em %lu us\n",
           ctx->update_count, arp_changes, (unsigned long)ctx->last_update_us);
}

uint8_t routing_next_hop(routing_ctx_t *ctx, uint8_t dest_id) {
    if (dest_id == 0 || dest_id > RL_MAX_NODES) return 0;
    pthread_mutex_lock(&ctx->lock);
    uint8_t nh = ctx->next_hop[dest_id];
    pthread_mutex_unlock(&ctx->lock);
    return nh;
}

void routing_print(routing_ctx_t *ctx) {
    pthread_mutex_lock(&ctx->lock);
    printf("\n+===== ROUTING MATRIX (Ana) — Node %u =====+\n", ctx->my_node_id);
    for (routingList_t *p = ctx->primary; p; p = p->next) {
        printf("| direct %2u (%02x:%02x:%02x:%02x:%02x:%02x):",
               p->id, p->macAddress[0], p->macAddress[1], p->macAddress[2],
               p->macAddress[3], p->macAddress[4], p->macAddress[5]);
        for (routingList_t *s = p->accessibleNodes; s; s = s->next)
            printf(" %u", s->id);
        printf("\n");
    }
    if (!ctx->primary) printf("|   (sem vizinhos directos)\n");
    printf("+==========================================+\n\n");
    pthread_mutex_unlock(&ctx->lock);
}
