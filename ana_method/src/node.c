/*
 * ═══════════════════════════════════════════════════════════════
 * node.c — Framework RA-TDMAs+  (MÉTODO ANA MORAIS, recriação fiel)
 *
 * Diferenças face ao método Miguel (projeto principal):
 *   • Transporte 100% UDP no framework (sem TCP, sem tcp_sockfd[]).
 *   • SEM separação MSG_DATA — dados = pacote IP raw, relay
 *     transparente (a app vê sempre o src original).
 *   • MST binária (Prim sem link quality).
 *   • Routing matrix em linked list + tabela ARP via ioctl().
 *   • MAC partilhado no state packet (trailer de 6 bytes).
 *
 * Pacotes no ar (todos UDP, porta BASE_PORT + id):
 *   STATE: [tdma_header(MATRIX)][matriz serializada][MAC 6 bytes]
 *   DATA : [tdma_header(MSG_DATA)][pacote IP raw]
 * ═══════════════════════════════════════════════════════════════
 */

#include "node.h"
#include "matrix.h"
#include "tun.h"
#include "sync.h"
#include "tx_queue.h"
#include "mac_table.h"
#include "routing_list.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <signal.h>
#include <sys/time.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>

#define BASE_PORT        7000
#define SLOT_DURATION_US 50000
#define GUARD_US         5000
#define WIFI_BPS         24000000ULL
#define T_TRANS_US(len)  ((len) * 8ULL * 1000000ULL / WIFI_BPS)
#define SLOT_USEFUL_US   (SLOT_DURATION_US - GUARD_US)
#define MAX_BYTES_SLOT   ((SLOT_USEFUL_US / T_TRANS_US(1500)) * 1500ULL)

#ifndef MESH_NET_PREFIX
#define MESH_NET_PREFIX "172.20.10"   /* prefixo físico (ad-hoc) */
#endif
#ifndef MESH_PHY_IFACE
#define MESH_PHY_IFACE "wlan0"
#endif

#define MESH_VIRT_PREFIX "10.0.0"     /* prefixo virtual (TUN / destinos) */

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

static inline void phy_node_ip(char *buf, size_t len, uint8_t id) {
    snprintf(buf, len, "%s.%u", MESH_NET_PREFIX, id);
}

/* ═══════════════════════════════════════════════════════════════
 * THREAD TUN — lê pacotes IP da app e enfileira para o slot
 * ═══════════════════════════════════════════════════════════════ */
static void* tun_reader_loop(void *arg) {
    node_t *node = (node_t *)arg;
    uint8_t buf[TUN_MTU + 4];

    if (node->tun_fd >= 0) {
        int fl = fcntl(node->tun_fd, F_GETFL, 0);
        fcntl(node->tun_fd, F_SETFL, fl & ~O_NONBLOCK);
    }
    printf("[TUN] Thread iniciada (fd=%d)\n", node->tun_fd);

    while (node->running && g_running) {
        if (node->tun_fd < 0) break;
        ssize_t n = tun_read(node->tun_fd, buf, sizeof(buf));
        if (n <= 0) continue;
        uint8_t dst = tun_get_dst_node(buf, (size_t)n);
        if (dst != 0 && dst != node->node_id) {
            tx_queue_push(node->tx_queue, buf, (size_t)n, dst);
            printf("[TUN] Pacote %zd bytes  dst=%u  queue=%d\n",
                   n, dst, tx_queue_size(node->tx_queue));
        }
    }
    printf("[TUN] Thread terminada\n");
    return NULL;
}

/* ═══════════════════════════════════════════════════════════════
 * THREAD RX — socket UDP único: STATE (MATRIX) e DATA (IP raw)
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

        if (hdr->type == MATRIX) {
            /* trailer: últimos 6 bytes = MAC do emissor (tese 3.2.3) */
            if (n >= (ssize_t)(sizeof(tdma_header_t) + 6)) {
                const uint8_t *mac = buffer + (n - 6);
                mac_table_set(hdr->slot_id, mac);
            }
            sync_record_delay(hdr->slot_id, hdr->timestamp,
                              hdr->slot_begin_ms, hdr->slot_end_ms, rp_ms);
            /* exclui o trailer MAC ao dar a matriz ao parser */
            MATRIX_parsePkt(buffer, n - 6, hdr->slot_id);
            printf("[RX] STATE de Node %u (%zd bytes)\n", hdr->slot_id, n);

        } else if (hdr->type == MSG_DATA) {
            /* dados = pacote IP raw logo após o cabeçalho TDMA */
            uint8_t *ip_pkt = buffer + sizeof(tdma_header_t);
            uint16_t ip_len = (uint16_t)(n - sizeof(tdma_header_t));
            if (ip_len < 20) continue;

            uint8_t final_dst = tun_get_dst_node(ip_pkt, ip_len);

            if (final_dst == node->node_id) {
                /* entrega local — a app vê o src original (transparente) */
                printf("[RX] DATA ENTREGUE  dst=%u  %u bytes IP\n",
                       final_dst, ip_len);
                if (node->tun_fd >= 0)
                    tun_write(node->tun_fd, ip_pkt, ip_len);
            } else if (final_dst != 0) {
                /* relay transparente: reenfileira para reenviar no meu slot */
                printf("[RX] RELAY  dst=%u  (reencaminha no meu slot)\n", final_dst);
                tx_queue_push(node->tx_queue, ip_pkt, ip_len, final_dst);
            }
        }
    }
    printf("[RX] Thread terminada\n");
    return NULL;
}

/* Envia um pacote DATA (IP raw) por UDP ao IP físico do next-hop */
static ssize_t send_data_udp(node_t *node, uint8_t next_hop,
                             const uint8_t *ip_pkt, uint16_t ip_len,
                             uint32_t seq) {
    uint8_t pkt[2048];
    tdma_header_t *hdr = (tdma_header_t *)pkt;
    memset(hdr, 0, sizeof(*hdr));
    hdr->type    = MSG_DATA;
    hdr->slot_id = node->node_id;
    hdr->seq_num = seq;
    hdr->timestamp = (double)get_time_us() / 1000000.0;
    memcpy(pkt + sizeof(tdma_header_t), ip_pkt, ip_len);
    int total = sizeof(tdma_header_t) + ip_len;

    struct sockaddr_in dst = {0};
    dst.sin_family = AF_INET;
    dst.sin_port   = htons(BASE_PORT + next_hop);
    dst.sin_addr.s_addr = inet_addr(node->peer_ips[next_hop]);
    return sendto(node->sockfd, pkt, total, 0,
                  (struct sockaddr *)&dst, sizeof(dst));
}

/* ═══════════════════════════════════════════════════════════════
 * THREAD TX — ronda TDMA: actualiza rotas, difunde STATE, drena DATA
 * ═══════════════════════════════════════════════════════════════ */
static void* tx_loop(void *arg) {
    node_t  *node = (node_t *)arg;
    uint8_t  pkt_buffer[4096];
    uint32_t tx_counter = 0;
    uint16_t rp_ms = round_period_ms(node->num_nodes);

    printf("[TX] Thread iniciada, Slot %d  frame=%u ms\n",
           node->node_id - 1, rp_ms);

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

        /* ── 1. Actualiza routing matrix a partir da MST refrescada ── */
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
            /* trailer MAC */
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
            printf("[TX] Slot %d: STATE (%d bytes seq=%u)\n",
                   current_slot, total_len, tx_counter - 1);
            MATRIX_print();
        }

        /* ── 3. Drena DATA (IP raw, relay transparente) ── */
        uint32_t pkts = 0;
        uint64_t bytes = 0;
        tx_pkt_t *p;
        while ((p = tx_queue_pop(node->tx_queue)) != NULL) {
            if (get_time_us() >= slot_end) {
                tx_queue_push(node->tx_queue, p->data, p->len, p->dst_id);
                free(p);
                break;
            }
            uint8_t nh = routing_next_hop(node->routing, p->dst_id);
            if (nh == 0 || node->peer_ips[nh][0] == '\0') {
                printf("[TX] Sem rota para Node %u — descartado\n", p->dst_id);
                free(p);
                continue;
            }
            if (bytes + sizeof(tdma_header_t) + p->len > MAX_BYTES_SLOT) {
                tx_queue_push(node->tx_queue, p->data, p->len, p->dst_id);
                free(p);
                break;
            }
            ssize_t sent = send_data_udp(node, nh, p->data, (uint16_t)p->len,
                                         tx_counter++);
            printf("[TX] DATA  dst=%u  next_hop=%u(%s)  ip_len=%zu  sent=%zd\n",
                   p->dst_id, nh, node->peer_ips[nh], p->len, sent);
            if (sent > 0) { pkts++; bytes += (uint64_t)sent; }
            free(p);
        }

        if (pkts)
            printf("[SLOT] pkts=%u  bytes=%lu\n", pkts, (unsigned long)bytes);

        sync_adjust_slot(rp_ms);

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

    printf("\n====================================================\n");
    printf("  RA-TDMAs+  Node %u  (MÉTODO ANA MORAIS — UDP/ARP)\n", node_id);
    printf("====================================================\n");
    printf("[Node %u] Porta=%d  Slot=%d  Frame=%.1fms\n",
           node_id, node->port, node_id - 1, node->frame_duration_us / 1000.0);

    node->sockfd = socket(AF_INET, SOCK_DGRAM, 0);
    if (node->sockfd < 0) { perror("socket"); free(node); return NULL; }
    int reuse = 1;
    setsockopt(node->sockfd, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));

    memset(node->peer_ips, 0, sizeof(node->peer_ips));
    for (int i = 1; i <= num_nodes; i++)
        phy_node_ip(node->peer_ips[i], sizeof(node->peer_ips[i]), (uint8_t)i);

    struct sockaddr_in addr = {0};
    addr.sin_family      = AF_INET;
    addr.sin_port        = htons(node->port);
    addr.sin_addr.s_addr = INADDR_ANY;
    if (bind(node->sockfd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("bind"); close(node->sockfd); free(node); return NULL;
    }

    MATRIX_init(node_id);
    mac_table_init();
    if (mac_table_local_mac(MESH_PHY_IFACE, node->my_mac) != 0) {
        fprintf(stderr, "[Node %u] AVISO: não consegui ler MAC de %s\n",
                node_id, MESH_PHY_IFACE);
    } else {
        printf("[Node %u] MAC local (%s): %02x:%02x:%02x:%02x:%02x:%02x\n",
               node_id, MESH_PHY_IFACE,
               node->my_mac[0], node->my_mac[1], node->my_mac[2],
               node->my_mac[3], node->my_mac[4], node->my_mac[5]);
    }

    node->routing  = routing_create(node_id, MESH_VIRT_PREFIX, MESH_PHY_IFACE);
    node->tx_queue = tx_queue_create();

    sync_init(node_id, num_nodes, (uint16_t)(node->frame_duration_us / 1000));

    node->tun_fd = tun_open(node_id);
    if (node->tun_fd < 0)
        fprintf(stderr, "[Node %u] ERRO: TUN não aberta\n", node_id);

    return node;
}

void node_run(node_t *node) {
    signal(SIGINT, on_sigint);
    printf("[Node %u] Iniciando threads...\n\n", node->node_id);

    pthread_create(&node->receiver_thread, NULL, receiver_loop,   node);
    pthread_create(&node->tx_thread,       NULL, tx_loop,         node);
    if (node->tun_fd >= 0)
        pthread_create(&node->tun_thread,  NULL, tun_reader_loop, node);

    pthread_join(node->receiver_thread, NULL);
    pthread_join(node->tx_thread,       NULL);
    if (node->tun_fd >= 0)
        pthread_join(node->tun_thread,  NULL);

    printf("\n[Node %u] Threads terminadas\n", node->node_id);
}

void node_destroy(node_t *node) {
    if (!node) return;
    uint8_t id = node->node_id;
    node->running = 0;
    if (node->tun_fd >= 0) tun_close(node->tun_fd, node->node_id);
    if (node->routing)     routing_destroy(node->routing);
    if (node->tx_queue)    tx_queue_destroy(node->tx_queue);
    close(node->sockfd);
    free(node);
    printf("[Node %u] Destruído\n", id);
}
