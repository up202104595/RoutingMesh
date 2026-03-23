/*
 * ═══════════════════════════════════════════════════════════════
 * node.c  —  RA-TDMAs+  Node  (Layer 3 + TUN + MSG_DATA)
 *
 * 4 threads:
 *   RX    — recvfrom() → MATRIX_parsePkt() | MSG_DATA → tun_write()
 *   TX    — slot TDMA  → MATRIX broadcast + tx_queue drain (MSG_DATA)
 *   EH    — event_queue_pop() → routing_manager_recompute() + ip_route_add
 *   TUN   — tun_read() → tx_queue_push()
 * ═══════════════════════════════════════════════════════════════
 */

#include "node.h"
#include "matrix.h"
#include "routing.h"
#include "event_handler.h"
#include "ip_route_netlink.h"
#include "tx_queue.h"
#include "tun.h"
#include "msg_data.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <pthread.h>
#include <signal.h>
#include <fcntl.h>

#define BASE_PORT        7000
#define SLOT_DURATION_US 200000
#define GUARD_US         5000   /* margem no fim do slot: não envia nos últimos 5ms */

/* Prefixo da rede física mesh.
 * Cada nó tem IP <MESH_NET_PREFIX>.<node_id> na interface física (wlan0/eth0).
 * Em testes locais (loopback) usa 127.0.0. — todos os nós na mesma máquina.
 * Em produção (WiFi real / Raspberry) usa 192.168.2.            */
#ifndef MESH_NET_PREFIX
#define MESH_NET_PREFIX  "127.0.0"   /* loopback para testes locais */
#endif

/* Constrói o IP físico de um nó: <MESH_NET_PREFIX>.<node_id> */
static inline void mesh_node_ip(char *buf, size_t buf_len, uint8_t node_id) {
    snprintf(buf, buf_len, "%s.%u", MESH_NET_PREFIX, node_id);
}

static volatile int g_running = 1;
event_queue_t *g_event_queue = NULL;

void signal_handler(int sig) {
    (void)sig;
    g_running = 0;
    printf("\n[SIGNAL] Ctrl+C recebido, parando...\n");
}

uint64_t get_time_us(void) {
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return (uint64_t)tv.tv_sec * 1000000 + tv.tv_usec;
}

// ═══════════════════════════════════════════════════════════════
// THREAD TUN  —  lê pacotes IP de tun0 e coloca na tx_queue
// ═══════════════════════════════════════════════════════════════

/* ─────────────────────────────────────────────────────────────
 * build_fake_icmp_pkt()
 *
 * Constrói um pacote IP+ICMP echo request fictício:
 *   src = 10.0.0.<src_id>
 *   dst = 10.0.0.<dst_id>
 *
 * Sem checksum real (kernel não verifica em TUN injectado).
 * Tamanho: 28 bytes  (20 IP header + 8 ICMP header)
 * ───────────────────────────────────────────────────────────── */
static size_t build_fake_icmp_pkt(uint8_t *buf, size_t buf_len,
                                   uint8_t src_id, uint8_t dst_id,
                                   uint16_t seq)
{
    if (buf_len < 28) return 0;

    memset(buf, 0, 28);

    /* ── IPv4 header (20 bytes) ── */
    buf[0]  = 0x45;               /* version=4, IHL=5 (20 bytes) */
    buf[1]  = 0x00;               /* DSCP/ECN                    */
    buf[2]  = 0x00; buf[3] = 28; /* total length = 28           */
    buf[4]  = (seq >> 8) & 0xFF;  /* identification (usa seq)    */
    buf[5]  = seq & 0xFF;
    buf[6]  = 0x00; buf[7] = 0x00; /* flags + frag offset        */
    buf[8]  = 64;                  /* TTL                         */
    buf[9]  = 0x01;                /* protocol = ICMP             */
    buf[10] = 0x00; buf[11] = 0x00; /* header checksum (0 = skip) */
    buf[12] = 10; buf[13] = 0; buf[14] = 0; buf[15] = src_id; /* src */
    buf[16] = 10; buf[17] = 0; buf[18] = 0; buf[19] = dst_id; /* dst */

    /* ── ICMP header (8 bytes) ── */
    buf[20] = 0x08;  /* type = echo request */
    buf[21] = 0x00;  /* code = 0            */
    buf[22] = 0x00; buf[23] = 0x00; /* checksum (0 = skip) */
    buf[24] = src_id;               /* identifier          */
    buf[25] = dst_id;
    buf[26] = (seq >> 8) & 0xFF;   /* sequence number     */
    buf[27] = seq & 0xFF;

    return 28;
}

void* tun_reader_loop(void *arg) {
    node_t *node = (node_t *)arg;
    uint8_t buf[TUN_MTU + 4];
    uint16_t fake_seq = 0;

    printf("[TUN] Thread iniciada (fd=%d) — modo: TUN real + gerador ficticio\n",
           node->tun_fd);

    /* tun_fd em modo não-bloqueante para alternar leitura real / gerador */
    if (node->tun_fd >= 0) {
        int flags = fcntl(node->tun_fd, F_GETFL, 0);
        fcntl(node->tun_fd, F_SETFL, flags | O_NONBLOCK);
    }

    uint64_t last_fake_us = 0;
#define FAKE_INTERVAL_US 1000000   /* 1 pacote fictício por segundo por destino */

    while (node->running && g_running) {

        /* ── 1. Tenta ler pacote real da TUN (não bloqueia) ── */
        if (node->tun_fd >= 0) {
            ssize_t n = tun_read(node->tun_fd, buf, sizeof(buf));
            if (n > 0) {
                uint8_t dst_id = tun_get_dst_node(buf, (size_t)n);
                if (dst_id != 0 && dst_id != node->node_id) {
                    tx_queue_push(node->tx_queue, buf, (size_t)n, dst_id);
                    printf("[TUN] 📦 Pacote REAL: %zd bytes  dst=%d  queue=%d\n",
                           n, dst_id, tx_queue_size(node->tx_queue));
                }
            }
        }

        /* ── 2. Gerador fictício: 1 pacote/s para cada nó conhecido ── */
        uint64_t now = get_time_us();
        if (now - last_fake_us >= FAKE_INTERVAL_US) {
            last_fake_us = now;

            tdma_matrix_t *mat = MATRIX_get();
            for (int i = 0; i < mat->numberOfActiveNodes; i++) {
                uint8_t dst_id = mat->idOfActiveNodes[i];
                if (dst_id == node->node_id) continue;  /* não envia para si */

                size_t pkt_len = build_fake_icmp_pkt(buf, sizeof(buf),
                                                      node->node_id, dst_id,
                                                      fake_seq++);
                if (pkt_len == 0) continue;

                tx_queue_push(node->tx_queue, buf, pkt_len, dst_id);

                printf("[TUN] 🔧 Pacote FICTICIO: ICMP echo  src=10.0.0.%d  "
                       "dst=10.0.0.%d  seq=%u  queue=%d\n",
                       node->node_id, dst_id, fake_seq - 1,
                       tx_queue_size(node->tx_queue));
            }
        }

        usleep(10000);  /* 10ms — evita busy-wait */
    }

    printf("[TUN] Thread terminada\n");
    return NULL;
}

// ═══════════════════════════════════════════════════════════════
// THREAD RX
// ═══════════════════════════════════════════════════════════════

void* receiver_loop(void *arg) {
    node_t *node = (node_t *)arg;
    uint8_t buffer[2048];
    struct sockaddr_in src;
    socklen_t len = sizeof(src);

    printf("[RX] Thread iniciada, porta %d\n", node->port);

    while (node->running && g_running) {
        ssize_t n = recvfrom(node->sockfd, buffer, sizeof(buffer), 0,
                             (struct sockaddr *)&src, &len);
        if (n <= 0) continue;

        tdma_header_t *hdr = (tdma_header_t *)buffer;

        if (hdr->type == MATRIX) {
            MATRIX_parsePkt(buffer, n, hdr->slot_id);
            printf("[RX] MATRIX de Node %d (%zd bytes)\n", hdr->slot_id, n);

        } else if (hdr->type == MSG_DATA) {
            if ((size_t)n < sizeof(tdma_header_t) + sizeof(msg_data_hdr_t))
                continue;

            msg_data_hdr_t *data = (msg_data_hdr_t *)(buffer + sizeof(tdma_header_t));
            uint8_t  *ip_pkt = data->payload;
            uint16_t  ip_len = data->data_len;

            if (data->dst_id == node->node_id) {
                /*
                 * Sou o destino final.
                 * Escreve o pacote IP original em tun0 →
                 * a aplicação local recebe-o transparentemente.
                 */
                printf("[RX] MSG_DATA ENTREGUE  src=%d dst=%d "
                       "msg_id=%u  %u bytes IP\n",
                       data->src_id, data->dst_id,
                       data->msg_id, ip_len);

                if (node->tun_fd >= 0)
                    tun_write(node->tun_fd, ip_pkt, ip_len);

            } else {
                /*
                 * Nó intermédio (relay) ou destino não final.
                 * Reinjecta o pacote IP original na wlan0 via raw socket.
                 * O kernel com ip_forward=1 + ip route faz forward automático
                 * se IP dst != eu, ou entrega à aplicação se IP dst == eu.
                 */
                msg_data_hdr_t *data2 = (msg_data_hdr_t *)(buffer + sizeof(tdma_header_t));
                printf("[RX] RELAY  src=%d dst=%d → reinjecta via raw socket\n",
                       data2->src_id, data2->dst_id);
                tun_write(node->tun_fd, data2->payload, data2->data_len);
            }
        }
    }

    printf("[RX] Thread terminada\n");
    return NULL;
}

// ═══════════════════════════════════════════════════════════════
// THREAD TX
// ═══════════════════════════════════════════════════════════════

void* tx_loop(void *arg) {
    node_t *node = (node_t *)arg;
    uint8_t  pkt_buffer[2048];
    uint32_t tx_counter  = 0;
    uint16_t data_msg_id = 0;

    struct sockaddr_in dest = {0};
    dest.sin_family = AF_INET;

    printf("[TX] Thread iniciada, TDMA Slot %d\n", node->node_id - 1);

    while (node->running && g_running) {
        uint64_t now           = get_time_us();
        uint64_t time_in_frame = now % node->frame_duration_us;
        int      current_slot  = (int)(time_in_frame / SLOT_DURATION_US);

        if (current_slot != (node->node_id - 1)) {
            usleep(2000);
            continue;
        }

        /* calcula fim do slot com margem de guarda */
        uint64_t slot_end = (now - time_in_frame) +
                            ((uint64_t)(current_slot + 1) * SLOT_DURATION_US)
                            - GUARD_US;

        /* ── ① MATRIX broadcast ── */
        void *matrix_payload = serializeMatrix(*MATRIX_get());
        if (matrix_payload) {
            uint16_t idSize, matSize, ageSize;
            parameterSize(&idSize, &matSize, &ageSize,
                          MATRIX_get()->numberOfActiveNodes);
            int payload_len = sizeof(uint8_t) + idSize + matSize + ageSize;

            tdma_header_t *hdr = (tdma_header_t *)pkt_buffer;
            hdr->type      = MATRIX;
            hdr->slot_id   = node->node_id;
            hdr->seq_num   = tx_counter++;
            hdr->timestamp = (double)now / 1000000.0;
            memcpy(pkt_buffer + sizeof(tdma_header_t), matrix_payload, payload_len);
            free(matrix_payload);

            int total_len = sizeof(tdma_header_t) + payload_len;
            for (int i = 1; i <= node->num_nodes; i++) {
                if (i == node->node_id) continue;
                char node_ip[32];
                mesh_node_ip(node_ip, sizeof(node_ip), (uint8_t)i);
                dest.sin_addr.s_addr = inet_addr(node_ip);
                dest.sin_port        = htons(BASE_PORT + i);
                sendto(node->sockfd, pkt_buffer, total_len, 0,
                       (struct sockaddr *)&dest, sizeof(dest));
            }
            printf("[TX] Slot %d: MATRIX (%d bytes seq=%u)\n",
                   current_slot, total_len, tx_counter - 1);
            MATRIX_print();
        }

        /* ── ② MSG_DATA unicast — drena tx_queue até fim do slot ──
         *
         * Para cada pacote na fila:
         *   1. lookup next_hop via routing_manager
         *   2. encapsula em MSG_DATA (tdma_header + msg_data_hdr + IP_raw)
         *   3. sendto(IP_next_hop, porta_destino)
         *
         * Para quando o slot está a acabar (GUARD_US de margem).
         */
        tx_pkt_t *pkt;
        while ((pkt = tx_queue_pop(node->tx_queue)) != NULL) {

            /* verifica tempo restante */
            if (get_time_us() >= slot_end) {
                /* devolve à fila (reinsere à frente) — não perdemos o pacote */
                tx_queue_push(node->tx_queue, pkt->data, pkt->len, pkt->dst_id);
                free(pkt);
                break;
            }

            uint8_t next_hop = routing_manager_lookup(node->routing, pkt->dst_id);
            if (next_hop == 0) {
                printf("[TX] Sem rota para Node %d, pacote descartado\n",
                       pkt->dst_id);
                free(pkt);
                continue;
            }

            /* constrói pacote MSG_DATA */
            tdma_header_t  *hdr  = (tdma_header_t *)pkt_buffer;
            msg_data_hdr_t *data = (msg_data_hdr_t *)(pkt_buffer + sizeof(tdma_header_t));

            hdr->type      = MSG_DATA;
            hdr->slot_id   = node->node_id;
            hdr->seq_num   = tx_counter++;
            hdr->timestamp = (double)get_time_us() / 1000000.0;

            data->src_id  = node->node_id;
            data->dst_id  = pkt->dst_id;
            data->msg_id  = data_msg_id++;
            data->data_len = (uint16_t)pkt->len;

            /* copia pacote IP raw no payload */
            memcpy(data->payload, pkt->data, pkt->len);
            free(pkt);

            int total_len = sizeof(tdma_header_t) + sizeof(msg_data_hdr_t);

            /* envia para o IP real do next_hop */
            const char *next_hop_ip = node->peer_ips[next_hop];
            if (next_hop_ip[0] == '\0') {
                printf("[TX] IP desconhecido para next_hop=%d\n", next_hop);
                continue;
            }
            dest.sin_addr.s_addr = inet_addr(next_hop_ip);
            dest.sin_port        = htons(BASE_PORT + data->dst_id);

            ssize_t sent = sendto(node->sockfd, pkt_buffer, total_len, 0,
                                  (struct sockaddr *)&dest, sizeof(dest));

            printf("[TX] MSG_DATA  dst=%d  next_hop=%d(%s)  "
                   "msg_id=%u  ip_len=%u  sent=%zd\n",
                   data->dst_id, next_hop, next_hop_ip,
                   data->msg_id, data->data_len, sent);
        }

        /* dorme até ao fim do slot */
        uint64_t now2 = get_time_us();
        if (now2 < slot_end + GUARD_US) {
            uint64_t sleep_time = slot_end + GUARD_US - now2;
            if (sleep_time < SLOT_DURATION_US)
                usleep(sleep_time);
        }
    }

    printf("[TX] Thread terminada\n");
    return NULL;
}

// ═══════════════════════════════════════════════════════════════
// NODE INIT
// ═══════════════════════════════════════════════════════════════

node_t* node_init(uint8_t node_id, uint8_t num_nodes) {
    node_t *node = calloc(1, sizeof(node_t));
    if (!node) { perror("calloc"); return NULL; }

    node->node_id           = node_id;
    node->num_nodes         = num_nodes;
    node->port              = BASE_PORT + node_id;
    node->running           = 1;
    node->frame_duration_us = (uint64_t)num_nodes * SLOT_DURATION_US;

    printf("\n╔════════════════════════════════════════════════════════╗\n");
    printf("║  RA-TDMAs+  Node %d  (Layer3 + TUN + MSG_DATA)       ║\n", node_id);
    printf("╚════════════════════════════════════════════════════════╝\n");
    printf("[Node %d] Porta=%d  Slot=%d  Frame=%.1fms\n\n",
           node_id, node->port, node_id - 1,
           node->frame_duration_us / 1000.0);

    /* socket UDP */
    node->sockfd = socket(AF_INET, SOCK_DGRAM, 0);
    if (node->sockfd < 0) { perror("socket"); free(node); return NULL; }

    int reuse = 1;
    setsockopt(node->sockfd, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
    int broadcast = 1;
    setsockopt(node->sockfd, SOL_SOCKET, SO_BROADCAST, &broadcast, sizeof(broadcast));

    /* preenche mapa node_id → IP físico automaticamente
     * usando MESH_NET_PREFIX definido em compilação.
     * Para testes locais: 127.0.0.1, 127.0.0.2, ...
     * Para produção WiFi: 192.168.2.1, 192.168.2.2, ... */
    memset(node->peer_ips, 0, sizeof(node->peer_ips));
    for (int i = 1; i <= num_nodes; i++) {
        mesh_node_ip(node->peer_ips[i], sizeof(node->peer_ips[i]), (uint8_t)i);
        printf("[Node %d] peer_ips[%d] = %s\n", node_id, i, node->peer_ips[i]);
    }

    struct sockaddr_in addr = {0};
    addr.sin_family      = AF_INET;
    addr.sin_port        = htons(node->port);
    addr.sin_addr.s_addr = INADDR_ANY;

    if (bind(node->sockfd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("bind"); close(node->sockfd); free(node); return NULL;
    }

    /* subsistemas */
    MATRIX_init(node_id);
    node->routing     = routing_manager_create(node_id, num_nodes);
    node->event_queue = event_queue_create();
    node->tx_queue    = tx_queue_create();
    g_event_queue     = node->event_queue;

    /* ip_forward */
    if (ip_forward_enable() != 0)
        fprintf(stderr, "[Node %d] AVISO: ip_forward nao activado (root?)\n",
                node_id);

    /* interface TUN */
    node->tun_fd = tun_open(node_id);
    if (node->tun_fd < 0) {
        fprintf(stderr, "[Node %d] ERRO: nao foi possivel abrir TUN\n",
                node_id);
        /* não é fatal para testes sem TUN — mas MSG_DATA não funcionará */
    }

    return node;
}

// ═══════════════════════════════════════════════════════════════
// NODE RUN / DESTROY
// ═══════════════════════════════════════════════════════════════

void node_run(node_t *node) {
    signal(SIGINT, signal_handler);
    printf("[Node %d] Iniciando 4 threads...\n\n", node->node_id);

    pthread_create(&node->receiver_thread, NULL, receiver_loop,    node);
    pthread_create(&node->tx_thread,       NULL, tx_loop,          node);
    pthread_create(&node->event_thread,    NULL, event_handler_loop, node);

    /* Thread TUN só arranca se a interface foi criada */
    if (node->tun_fd >= 0)
        pthread_create(&node->tun_thread, NULL, tun_reader_loop, node);
    else
        printf("[Node %d] AVISO: Thread TUN nao iniciada (sem tun_fd)\n",
               node->node_id);

    pthread_join(node->receiver_thread, NULL);
    pthread_join(node->tx_thread,       NULL);
    pthread_join(node->event_thread,    NULL);
    if (node->tun_fd >= 0)
        pthread_join(node->tun_thread,  NULL);

    printf("\n[Node %d] Threads terminadas\n", node->node_id);
}

void node_destroy(node_t *node) {
    if (!node) return;
    uint8_t id = node->node_id;
    node->running = 0;

    if (node->event_queue) {
        node->event_queue->running = false;
        pthread_cond_broadcast(&node->event_queue->not_empty);
    }

    if (node->tun_fd >= 0) tun_close(node->tun_fd, node->node_id);
    if (node->routing)     routing_manager_destroy(node->routing);
    if (node->event_queue) event_queue_destroy(node->event_queue);
    if (node->tx_queue)    tx_queue_destroy(node->tx_queue);

    close(node->sockfd);
    free(node);
    printf("[Node %d] Destruido\n", id);
}