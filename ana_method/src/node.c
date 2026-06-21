/*
 * ═══════════════════════════════════════════════════════════════
 * node.c — Framework RA-TDMAs+  (MÉTODO ANA MORAIS — recriação literal)
 *
 * O framework é SÓ plano de controlo. O reencaminhamento de dados é
 * 100% do kernel Linux (ip_forward + tabela ARP estática), feito à
 * Camada 2 sobre wlan0 e NÃO gated pelo slot TDMA — exactamente como
 * na dissertação (Secções 3.2, 3.2.6 e 4.4). Os nós intermédios
 * reencaminham imediatamente, com a limitação de slot que a tese
 * assume.
 *
 * Plano de controlo (UDP, porta BASE_PORT + id, em slots TDMA):
 *   STATE: [tdma_header(MATRIX)][matriz serializada][MAC 6 bytes]
 *
 * Não há pacotes DATA no framework: as aplicações comunicam
 * directamente pelos IPs físicos (ex.: ping/iperf para 172.20.10.X)
 * e o kernel reencaminha via ARP.
 * ═══════════════════════════════════════════════════════════════
 */

#include "node.h"
#include "matrix.h"
#include "sync.h"
#include "mac_table.h"
#include "routing_list.h"
#include "net_ana.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <sys/time.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>

#define BASE_PORT        7000
#define SLOT_DURATION_US 50000
#define GUARD_US         5000

#ifndef MESH_NET_PREFIX
#define MESH_NET_PREFIX "172.20.10"   /* prefixo físico (ad-hoc, real L2) */
#endif
#ifndef MESH_PHY_IFACE
#define MESH_PHY_IFACE "wlan0"
#endif
#ifndef MESH_VIRT_PREFIX
#define MESH_VIRT_PREFIX "10.0.0"     /* prefixo mesh/tun (apps) */
#endif

static volatile int g_running = 1;
static void on_sigint(int s) { (void)s; g_running = 0; }

static uint64_t get_time_us(void) {
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return (uint64_t)tv.tv_sec * 1000000 + tv.tv_usec;
}

static inline uint16_t round_period_ms(uint8_t num_nodes) {
    return (uint16_t)(num_nodes * (SLOT_DURATION_US / 1000));
}

/* ═══════════════════════════════════════════════════════════════
 * THREAD RX — recebe STATE (topologia + MAC) dos vizinhos
 * ═══════════════════════════════════════════════════════════════ */
static void* receiver_loop(void *arg) {
    node_t *node = (node_t *)arg;
    uint8_t buffer[2048];
    uint16_t rp_ms = round_period_ms(node->num_nodes);

    printf("[RX] Thread iniciada, porta %d\n", node->port);

    while (node->running && g_running) {
        struct sockaddr_in src;
        socklen_t slen = sizeof(src);
        ssize_t n = recvfrom(node->sockfd, buffer, sizeof(buffer), 0,
                             (struct sockaddr *)&src, &slen);
        if (n <= (ssize_t)sizeof(tdma_header_t)) continue;

        tdma_header_t *hdr = (tdma_header_t *)buffer;
        if (hdr->type != MATRIX) continue;

        /* trailer: últimos 6 bytes = MAC do emissor (tese 3.2.3) */
        if (n >= (ssize_t)(sizeof(tdma_header_t) + 6)) {
            const uint8_t *mac = buffer + (n - 6);
            mac_table_set(hdr->slot_id, mac);
        }
        sync_record_delay(hdr->slot_id, hdr->timestamp,
                          hdr->slot_begin_ms, hdr->slot_end_ms, rp_ms);
        MATRIX_parsePkt(buffer, n - 6, hdr->slot_id);   /* exclui trailer MAC */
        printf("[RX] STATE de Node %u (%zd bytes)\n", hdr->slot_id, n);
    }
    printf("[RX] Thread terminada\n");
    return NULL;
}

/* ═══════════════════════════════════════════════════════════════
 * THREAD TX — no slot TDMA: actualiza rotas/ARP e difunde STATE
 * ═══════════════════════════════════════════════════════════════ */
static void* tx_loop(void *arg) {
    node_t  *node = (node_t *)arg;
    uint8_t  pkt_buffer[4096];
    uint32_t tx_counter = 0;

    printf("[TX] Thread iniciada, Slot %d  frame=%u ms\n",
           node->node_id - 1, round_period_ms(node->num_nodes));

    while (node->running && g_running) {
        uint64_t now = get_time_us();
        uint64_t time_in_frame = now % node->frame_duration_us;
        int current_slot = (int)(time_in_frame / SLOT_DURATION_US);

        if (current_slot != (node->node_id - 1)) {
            usleep(1000);
            continue;
        }

        uint64_t slot_end = (now - time_in_frame) +
                            ((uint64_t)(current_slot + 1) * SLOT_DURATION_US) - GUARD_US;

        /* ── 1. Recalcula routing matrix + tabela ARP a partir da MST ── */
        matrix_snapshot_t snap;
        MATRIX_get_snapshot(&snap);
        if (snap.numberOfActiveNodes > 1)
            routing_update(node->routing, snap.mst_ptrs,
                           snap.idOfActiveNodes, snap.numberOfActiveNodes);

        /* ── 2. Difunde STATE: tdma_header + matriz + MAC (6 bytes) ── */
        int payload_len = 0;
        void *matrix_payload = serializeMatrix(&payload_len);
        if (matrix_payload) {
            slot_limits_t sl   = sync_get_slot();
            tdma_header_t *hdr = (tdma_header_t *)pkt_buffer;
            memset(hdr, 0, sizeof(*hdr));
            hdr->type          = MATRIX;
            hdr->slot_id       = node->node_id;
            hdr->seq_num       = tx_counter++;
            hdr->timestamp     = (double)now / 1000000.0;
            hdr->slot_begin_ms = sl.begin_ms;
            hdr->slot_end_ms   = sl.end_ms;

            memcpy(pkt_buffer + sizeof(tdma_header_t), matrix_payload, payload_len);
            free(matrix_payload);
            memcpy(pkt_buffer + sizeof(tdma_header_t) + payload_len, node->my_mac, 6);
            int total_len = sizeof(tdma_header_t) + payload_len + 6;

            struct sockaddr_in dest = {0};
            dest.sin_family = AF_INET;
            for (int i = 1; i <= node->num_nodes; i++) {
                if (i == node->node_id) continue;
                dest.sin_port = htons(BASE_PORT + i);
                dest.sin_addr.s_addr = inet_addr(node->peer_ips[i]);
                sendto(node->sockfd, pkt_buffer, total_len, 0,
                       (struct sockaddr *)&dest, sizeof(dest));
            }
            printf("[TX] Slot %d: STATE (%d bytes seq=%u)  [%u-%u ms]\n",
                   current_slot, total_len, tx_counter - 1, sl.begin_ms, sl.end_ms);
            MATRIX_print();
        }

        sync_adjust_slot(round_period_ms(node->num_nodes));

        uint64_t now2 = get_time_us();
        if (now2 < slot_end + GUARD_US) {
            uint64_t st = slot_end + GUARD_US - now2;
            if (st < SLOT_DURATION_US) usleep(st);
        }
    }
    printf("[TX] Thread terminada\n");
    return NULL;
}

/* ═══════════════════════════════════════════════════════════════
 * INIT / RUN / DESTROY
 * ═══════════════════════════════════════════════════════════════ */
node_t* node_init(uint8_t node_id, uint8_t num_nodes) {
    node_t *node = calloc(1, sizeof(node_t));
    if (!node) { perror("calloc"); return NULL; }

    node->node_id           = node_id;
    node->num_nodes         = num_nodes;
    node->port              = BASE_PORT + node_id;
    node->running           = 1;
    node->frame_duration_us = (uint64_t)num_nodes * SLOT_DURATION_US;
    snprintf(node->phy_iface,   sizeof(node->phy_iface),   "%s", MESH_PHY_IFACE);
    snprintf(node->phy_prefix,  sizeof(node->phy_prefix),  "%s", MESH_NET_PREFIX);
    snprintf(node->mesh_prefix, sizeof(node->mesh_prefix), "%s", MESH_VIRT_PREFIX);

    printf("\n====================================================\n");
    printf("  RA-TDMAs+  Node %u  (MÉTODO ANA — relay de kernel/ARP)\n", node_id);
    printf("====================================================\n");
    printf("[Node %u] Porta=%d  Slot=%d  Frame=%.1fms  wlan0=%s.x  mesh=%s.x\n",
           node_id, node->port, node_id - 1, node->frame_duration_us / 1000.0,
           node->phy_prefix, node->mesh_prefix);

    /* ── setup: wlan0 ad-hoc + tun (IP mesh) + ip_forward + sysctl ── */
    node->tun_fd = net_ana_setup(node->phy_iface, node->phy_prefix,
                                 node->mesh_prefix, node_id);
    if (node->tun_fd < 0)
        fprintf(stderr, "[Node %u] AVISO: tun não criada\n", node_id);

    node->sockfd = socket(AF_INET, SOCK_DGRAM, 0);
    if (node->sockfd < 0) { perror("socket"); free(node); return NULL; }
    int reuse = 1;
    setsockopt(node->sockfd, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));

    memset(node->peer_ips, 0, sizeof(node->peer_ips));
    for (int i = 1; i <= num_nodes; i++)
        snprintf(node->peer_ips[i], sizeof(node->peer_ips[i]),
                 "%s.%u", node->phy_prefix, (uint8_t)i);

    struct sockaddr_in addr = {0};
    addr.sin_family      = AF_INET;
    addr.sin_port        = htons(node->port);
    addr.sin_addr.s_addr = INADDR_ANY;
    if (bind(node->sockfd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("bind"); close(node->sockfd); free(node); return NULL;
    }

    MATRIX_init(node_id);
    mac_table_init();
    if (net_ana_local_mac(node->phy_iface, node->my_mac) != 0)
        fprintf(stderr, "[Node %u] AVISO: não consegui ler MAC de %s\n",
                node_id, node->phy_iface);
    else
        printf("[Node %u] MAC local (%s): %02x:%02x:%02x:%02x:%02x:%02x\n",
               node_id, node->phy_iface,
               node->my_mac[0], node->my_mac[1], node->my_mac[2],
               node->my_mac[3], node->my_mac[4], node->my_mac[5]);

    /* rotas+ARP instaladas para os IPs MESH dos destinos, a sair por wlan0
     * (é o kernel que faz o relay via ARP — ver net_ana.c) */
    node->routing = routing_create(node_id, node->mesh_prefix, node->phy_iface);

    sync_init(node_id, num_nodes, (uint16_t)(node->frame_duration_us / 1000));
    return node;
}

void node_run(node_t *node) {
    signal(SIGINT, on_sigint);
    printf("[Node %u] Iniciando threads...\n\n", node->node_id);

    pthread_create(&node->receiver_thread, NULL, receiver_loop, node);
    pthread_create(&node->tx_thread,       NULL, tx_loop,       node);

    pthread_join(node->receiver_thread, NULL);
    pthread_join(node->tx_thread,       NULL);

    printf("\n[Node %u] Threads terminadas\n", node->node_id);
}

void node_destroy(node_t *node) {
    if (!node) return;
    uint8_t id = node->node_id;
    node->running = 0;
    net_ana_teardown(node->phy_iface, node->tun_fd, node->node_id);
    if (node->routing) routing_destroy(node->routing);
    close(node->sockfd);
    free(node);
    printf("[Node %u] Destruído\n", id);
}
