/*
 * ═══════════════════════════════════════════════════════════════
 * node.c — Framework RA-TDMAs+  (MÉTODO ANA MORAIS — recriação literal)
 *
 * Fluxo de dados (Figura 3.13 da tese):
 *   ORIGEM:  app -> (iptables mangle) -> tun -> framework lê -> UDP no
 *            slot para o IP de wlan0 do destino final (porta 7000+dst)
 *   RELAYS:  o KERNEL reencaminha via ARP/ip_forward, imediatos, dentro
 *            do slot da origem (não gated pelo slot) — 3.2.6
 *   DESTINO: framework recebe a UDP -> escreve o IP raw na tun -> app
 *
 * Pacotes no ar (UDP, porta 7000+id):
 *   STATE: [tdma_header(MATRIX)][matriz serializada][MAC 6 bytes]
 *   DATA : [tdma_header(MSG_DATA)][pacote IP raw da app]
 * ═══════════════════════════════════════════════════════════════
 */

#include "node.h"
#include "matrix.h"
#include "sync.h"
#include "mac_table.h"
#include "routing_list.h"
#include "net_ana.h"
#include "tx_queue.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <signal.h>
#include <sys/time.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <netinet/ip.h>
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

/* nó destino = último octeto do IP destino do pacote (id = X em a.b.c.X) */
static uint8_t ip_dst_node(const uint8_t *ip_pkt, size_t len) {
    if (len < sizeof(struct iphdr)) return 0;
    const struct iphdr *iph = (const struct iphdr *)ip_pkt;
    if (iph->version != 4) return 0;
    return (uint8_t)(ntohl(iph->daddr) & 0xFF);
}

/* Re-injecta um pacote IP raw no kernel via raw socket (tese 3.2.5):
 * SOCK_RAW/IPPROTO_RAW com IP_HDRINCL, ligado ao IP de DESTINO (não à
 * interface) para o kernel tratar routing/fragmentação. O kernel entrega
 * localmente se o destino for nosso, ou faz ip_forward via ARP se for de
 * outro nó. Relay 100% kernel, IP de origem intacto. */
static ssize_t raw_inject(const uint8_t *ip_pkt, size_t len) {
    if (len < sizeof(struct iphdr)) return -1;
    int s = socket(AF_INET, SOCK_RAW, IPPROTO_RAW);
    if (s < 0) { perror("[RX] raw socket"); return -1; }
    int one = 1;
    setsockopt(s, IPPROTO_IP, IP_HDRINCL, &one, sizeof(one));
    const struct iphdr *iph = (const struct iphdr *)ip_pkt;
    struct sockaddr_in dst = {0};
    dst.sin_family      = AF_INET;
    dst.sin_addr.s_addr = iph->daddr;          /* ligar ao destino (3.2.5) */
    ssize_t w = sendto(s, ip_pkt, len, 0,
                       (struct sockaddr *)&dst, sizeof(dst));
    if (w < 0) perror("[RX] sendto raw");
    close(s);
    return w;
}

/* ═══════════════════════════════════════════════════════════════
 * THREAD TUN — lê os pacotes de aplicação desviados para a tun e
 * enfileira-os para serem enviados no slot (Figura 3.13, origem)
 * ═══════════════════════════════════════════════════════════════ */
static void* tun_reader_loop(void *arg) {
    node_t *node = (node_t *)arg;
    uint8_t buf[2048];

    if (node->tun_fd >= 0) {
        int fl = fcntl(node->tun_fd, F_GETFL, 0);
        fcntl(node->tun_fd, F_SETFL, fl & ~O_NONBLOCK);
    }
    printf("[TUN] Thread iniciada (fd=%d)\n", node->tun_fd);

    while (node->running && g_running) {
        if (node->tun_fd < 0) break;
        ssize_t n = read(node->tun_fd, buf, sizeof(buf));
        if (n <= 0) continue;
        /* No método Ana os dados são encaminhados PELO KERNEL na subrede
         * mesh (rota /32 dev wlan0 + ARP estática instaladas pelo
         * routing_list). O framework NÃO reenvia dados por UDP: qualquer
         * pacote que ainda caia na tun (ex.: destino sem rota /32 antes da
         * convergência) é descartado — evita loop e mantém a origem na
         * subrede mesh, para o iptables -s <IP físico> não os apanhar. */
    }
    printf("[TUN] Thread terminada\n");
    return NULL;
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

        if (hdr->type == MATRIX) {
            /* trailer: últimos 6 bytes = MAC do emissor (tese 3.2.3) */
            if (n >= (ssize_t)(sizeof(tdma_header_t) + 6)) {
                const uint8_t *mac = buffer + (n - 6);
                mac_table_set(hdr->slot_id, mac);
            }
            sync_record_delay(hdr->slot_id, hdr->timestamp,
                              hdr->slot_begin_ms, hdr->slot_end_ms, rp_ms);
            MATRIX_parsePkt(buffer, n - 6, hdr->slot_id);   /* exclui trailer MAC */
            printf("[RX] STATE de Node %u (%zd bytes)\n", hdr->slot_id, n);

        } else if (hdr->type == MSG_DATA) {
            /* DATA = [tdma_header][pacote IP raw da app].
             * Entrega/relay 100% PELO KERNEL via raw socket (tese 3.2.5):
             * re-injectamos o IP raw com SOCK_RAW/IPPROTO_RAW ligado ao
             * IP de destino. O kernel processa o pacote — se o destino for
             * local entrega à app (com reassembly); se não, faz ip_forward
             * via a ARP estática (dst -> MAC do next-hop) para o próximo
             * salto. O IP de origem fica intacto (relay transparente). */
            uint8_t *ip_pkt = buffer + sizeof(tdma_header_t);
            ssize_t  ip_len = n - (ssize_t)sizeof(tdma_header_t);
            if (ip_len >= (ssize_t)sizeof(struct iphdr)) {
                ssize_t w = raw_inject(ip_pkt, (size_t)ip_len);
                uint8_t fd = ip_dst_node(ip_pkt, (size_t)ip_len);
                printf("[RX] DATA de Node %u dst=%u %zd bytes -> kernel (raw, %s)  sent=%zd\n",
                       hdr->slot_id, fd, ip_len,
                       fd == node->node_id ? "entrega local" : "relay ip_forward/ARP", w);
            }
        }
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

        /* ── 3. Drena DATA: envia os pacotes da app, no slot, por UDP
         * para o IP de wlan0 do destino final (porta 7000+dst). O kernel
         * usa a ARP estática (dst -> MAC do next-hop) e relaya hop a hop. */
        tx_pkt_t *p;
        while ((p = tx_queue_pop(node->tx_queue)) != NULL) {
            if (get_time_us() >= slot_end) {           /* respeita o fim do slot */
                tx_queue_push(node->tx_queue, p->data, p->len, p->dst_id);
                free(p);
                break;
            }
            if (node->peer_ips[p->dst_id][0] == '\0') { free(p); continue; }

            tdma_header_t *dh = (tdma_header_t *)pkt_buffer;
            memset(dh, 0, sizeof(*dh));
            dh->type    = MSG_DATA;
            dh->slot_id = node->node_id;
            dh->seq_num = tx_counter++;
            dh->timestamp = (double)get_time_us() / 1000000.0;
            memcpy(pkt_buffer + sizeof(tdma_header_t), p->data, p->len);
            int dlen = sizeof(tdma_header_t) + (int)p->len;

            struct sockaddr_in dd = {0};
            dd.sin_family = AF_INET;
            dd.sin_port   = htons(BASE_PORT + p->dst_id);          /* 7000+dst */
            dd.sin_addr.s_addr = inet_addr(node->peer_ips[p->dst_id]); /* wlan0 IP */
            ssize_t s = sendto(node->sockfd, pkt_buffer, dlen, 0,
                               (struct sockaddr *)&dd, sizeof(dd));
            printf("[TX] DATA dst=%u (%s:%d)  ip_len=%zu  sent=%zd\n",
                   p->dst_id, node->peer_ips[p->dst_id], BASE_PORT + p->dst_id,
                   p->len, s);
            free(p);
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

    /* Routing na subrede MESH (10.0.0.x): por destino instala uma rota /32
     * (dev wlan0, src = IP mesh local) + ARP estática (10.0.0.dst -> MAC do
     * next-hop) via ioctl SIOCSARP. As apps endereçam 10.0.0.x; o kernel
     * reenvia o IP cru hop-a-hop, com origem na subrede mesh. */
    node->routing  = routing_create(node_id, MESH_VIRT_PREFIX, node->phy_iface);
    node->tx_queue = tx_queue_create();

    sync_init(node_id, num_nodes, (uint16_t)(node->frame_duration_us / 1000));
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
    net_ana_teardown(node->phy_iface, node->tun_fd, node->node_id);
    if (node->routing)  routing_destroy(node->routing);
    if (node->tx_queue) tx_queue_destroy(node->tx_queue);
    close(node->sockfd);
    free(node);
    printf("[Node %u] Destruído\n", id);
}
