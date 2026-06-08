/*
 * node.c  —  RA-TDMAs+  Node  (Layer 3 + TUN + MSG_DATA + SYNC + WIFI QUALITY + PDR)
 */

#include "node.h"
#include "matrix.h"
#include "routing.h"
#include "event_handler.h"
#include "ip_route_netlink.h"
#include "tx_queue.h"
#include "tun.h"
#include "msg_data.h"
#include "sync.h"
#include "wifi_quality.h"
#include "pdr.h"
#ifdef RELAY_METHOD_ARP
#include "mac_table.h"
#endif
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
#include <errno.h>
#include <netinet/tcp.h>

#define BASE_PORT        7000
#define BASE_TCP_PORT    8000
#define SLOT_DURATION_US 50000
#define GUARD_US         5000

#define WIFI_BPS         24000000ULL
#define T_TRANS_US(len)  ((len) * 8ULL * 1000000ULL / WIFI_BPS)
#define SLOT_USEFUL_US   (SLOT_DURATION_US - GUARD_US)
#define MAX_BYTES_SLOT   ((SLOT_USEFUL_US / T_TRANS_US(1500)) * 1500ULL)

#ifndef MESH_NET_PREFIX
#define MESH_NET_PREFIX  "172.20.10"
#endif

static volatile int g_streaming_paused = 0;

void stream_pause(void) {
    if (!g_streaming_paused) {
        system("pkill -STOP rpicam-vid 2>/dev/null");
        system("pkill -STOP ffmpeg 2>/dev/null");
        g_streaming_paused = 1;
        printf("[STREAM] Streaming pausado\n");
    }
}

void stream_resume(void) {
    if (g_streaming_paused) {
        usleep(200000);
        system("pkill -CONT rpicam-vid 2>/dev/null");
        system("pkill -CONT ffmpeg 2>/dev/null");
        g_streaming_paused = 0;
        printf("[STREAM] Streaming retomado\n");
    }
}

static inline void mesh_node_ip(char *buf, size_t buf_len, uint8_t node_id) {
    snprintf(buf, buf_len, "%s.%u", MESH_NET_PREFIX, node_id);
}

static volatile int g_running = 1;
event_queue_t *g_event_queue = NULL;

/* último frame em que recebemos pacote de cada nó (para slot miss detection) */
static volatile uint64_t g_last_rx_frame[MAX_NODES + 1] = {0};

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

static inline uint16_t round_period_ms(uint8_t num_nodes) {
    return (uint16_t)(num_nodes * (SLOT_DURATION_US / 1000));
}

// ═══════════════════════════════════════════════════════════════
// TCP — MSG_DATA
// ═══════════════════════════════════════════════════════════════

static int tcp_connect_peer(const char *peer_ip, int peer_id) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) return -1;

    int opt = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &opt, sizeof(opt));
    setsockopt(fd, SOL_SOCKET, SO_KEEPALIVE, &opt, sizeof(opt));

    int keepidle = 5, keepintvl = 2, keepcnt = 3;
    setsockopt(fd, IPPROTO_TCP, TCP_KEEPIDLE,  &keepidle,  sizeof(keepidle));
    setsockopt(fd, IPPROTO_TCP, TCP_KEEPINTVL, &keepintvl, sizeof(keepintvl));
    setsockopt(fd, IPPROTO_TCP, TCP_KEEPCNT,   &keepcnt,   sizeof(keepcnt));

    struct sockaddr_in addr = {0};
    addr.sin_family      = AF_INET;
    addr.sin_port        = htons(BASE_TCP_PORT + peer_id);
    addr.sin_addr.s_addr = inet_addr(peer_ip);

    struct timeval tv = {2, 0};
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));

    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        close(fd);
        return -1;
    }

    /* Timeouts definidos aqui, no momento da criação — a thread RX
     * não precisa de os repetir e arriscar aplicá-los num fd já substituído */
    struct timeval tv_snd = {1, 0};  /* 1 s */
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv_snd, sizeof(tv_snd));
    struct timeval tv_rcv = {2, 0};
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv_rcv, sizeof(tv_rcv));

    printf("[TCP] Ligado ao peer %d (%s:%d)\n", peer_id, peer_ip, BASE_TCP_PORT + peer_id);
    return fd;
}

void* tcp_accept_loop(void *arg) {
    node_t *node = (node_t *)arg;
    printf("[TCP] Accept thread iniciada na porta %d\n", BASE_TCP_PORT + node->node_id);

    while (node->running && g_running) {
        struct sockaddr_in peer_addr;
        socklen_t peer_len = sizeof(peer_addr);
        int fd = accept(node->tcp_server_fd, (struct sockaddr *)&peer_addr, &peer_len);
        if (fd < 0) {
            if (node->running && g_running) perror("[TCP] accept");
            continue;
        }

        char peer_ip[32];
        inet_ntop(AF_INET, &peer_addr.sin_addr, peer_ip, sizeof(peer_ip));

        int peer_id = -1;
        for (int i = 1; i <= node->num_nodes; i++) {
            if (strcmp(node->peer_ips[i], peer_ip) == 0) { peer_id = i; break; }
        }

        if (peer_id < 0) {
            printf("[TCP] Ligacao desconhecida de %s — ignorada\n", peer_ip);
            close(fd); continue;
        }

        int opt = 1;
        setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &opt, sizeof(opt));

        /* Timeouts definidos aqui (accept) — mesma lógica do connect */
        struct timeval tv_snd = {1, 0};  /* 1 s */
        setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv_snd, sizeof(tv_snd));
        struct timeval tv_rcv = {2, 0};
        setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv_rcv, sizeof(tv_rcv));

        pthread_mutex_lock(&node->tcp_mutex);
        if (node->tcp_sockfd[peer_id] >= 0) {
            struct linger sl = {1, 0};
            setsockopt(node->tcp_sockfd[peer_id], SOL_SOCKET, SO_LINGER, &sl, sizeof(sl));
            close(node->tcp_sockfd[peer_id]);
            node->tcp_sockfd[peer_id] = -1;
        }
        node->tcp_sockfd[peer_id] = fd;
        pthread_mutex_unlock(&node->tcp_mutex);
        printf("[TCP] Peer %d ligado (%s)\n", peer_id, peer_ip);
    }

    printf("[TCP] Accept thread terminada\n");
    return NULL;
}

void node_tcp_reconnect(node_t *node, uint8_t peer_id) {
    if (peer_id < 1 || peer_id > node->num_nodes) return;
    if (node->tcp_sockfd[peer_id] >= 0) {
        close(node->tcp_sockfd[peer_id]);
        node->tcp_sockfd[peer_id] = -1;
    }
    const char *ip = node->peer_ips[peer_id];
    if (ip[0] == '\0') return;
    int fd = tcp_connect_peer(ip, peer_id);
    if (fd >= 0) node->tcp_sockfd[peer_id] = fd;
}

void* tcp_keepalive_loop(void *arg) {
    node_t *node = (node_t *)arg;
    printf("[TCP] Keepalive thread iniciada\n");
    sleep(2);

    while (node->running && g_running) {
        for (int i = 1; i <= node->num_nodes; i++) {
            if (i == node->node_id) continue;
            if (node->peer_ips[i][0] == '\0') continue;
            pthread_mutex_lock(&node->tcp_mutex);
            int cur_fd = node->tcp_sockfd[i];
            pthread_mutex_unlock(&node->tcp_mutex);

            if (cur_fd < 0) {
                int fd = tcp_connect_peer(node->peer_ips[i], i);
                if (fd >= 0) {
                    pthread_mutex_lock(&node->tcp_mutex);
                    node->tcp_sockfd[i] = fd;
                    pthread_mutex_unlock(&node->tcp_mutex);
                    printf("[TCP] Peer %d ligado\n", i);
                } else {
                    printf("[TCP] Peer %d nao disponivel — a tentar em 1s...\n", i);
                }
            } else {
                char probe;
                ssize_t r = recv(cur_fd, &probe, 1, MSG_PEEK | MSG_DONTWAIT);
                /* r==0: FIN (peer fechou graciosamente)
                 * r<0 && errno != EAGAIN/EWOULDBLOCK: RST ou erro real */
                bool dead = (r == 0) ||
                            (r < 0 && errno != EAGAIN && errno != EWOULDBLOCK);
                if (dead) {
                    printf("[TCP] Peer %d socket morto (r=%zd errno=%d) — a reconectar\n",
                           i, r, errno);
                    pthread_mutex_lock(&node->tcp_mutex);
                    if (node->tcp_sockfd[i] == cur_fd) {
                        close(cur_fd);
                        node->tcp_sockfd[i] = -1;
                    }
                    pthread_mutex_unlock(&node->tcp_mutex);
                }
            }
        }
        sleep(1);
        if (!node->running || !g_running) break;
    }

    printf("[TCP] Keepalive thread terminada\n");
    return NULL;
}

// ═══════════════════════════════════════════════════════════════
// THREAD RX TCP
// ═══════════════════════════════════════════════════════════════

typedef struct { node_t *node; int peer_id; } tcp_rx_arg_t;

void* tcp_rx_peer_loop(void *arg) {
    tcp_rx_arg_t *rx_arg = (tcp_rx_arg_t *)arg;
    node_t *node    = rx_arg->node;
    int     peer_id = rx_arg->peer_id;
    free(rx_arg);

    uint8_t buffer[4096];
    printf("[TCP-RX] Thread para peer %d iniciada\n", peer_id);

    while (node->running && g_running) {
        pthread_mutex_lock(&node->tcp_mutex);
        int tcp_fd = node->tcp_sockfd[peer_id];
        pthread_mutex_unlock(&node->tcp_mutex);
        if (tcp_fd < 0) { usleep(100000); continue; }

        /* SO_RCVTIMEO (2s) já foi definido em tcp_connect_peer/tcp_accept_loop
         * no momento da criação do fd — não repetir aqui para não arriscar
         * aplicar num fd já substituído por outra thread */

        /* Lê 4 bytes de tamanho primeiro */
        uint32_t net_len = 0;
        ssize_t n = recv(tcp_fd, &net_len, 4, MSG_WAITALL);
        if (n != 4) {
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                /* Timeout — verifica se fd mudou */
                continue;
            }
            printf("[TCP-RX] Peer %d desligou\n", peer_id);
            /* Só fecha se o fd ainda for o mesmo — evita race condition */
            pthread_mutex_lock(&node->tcp_mutex);
            if (node->tcp_sockfd[peer_id] == tcp_fd) {
                close(tcp_fd);
                node->tcp_sockfd[peer_id] = -1;
            }
            pthread_mutex_unlock(&node->tcp_mutex);
            usleep(500000);
            continue;
        }

        uint32_t pkt_len = ntohl(net_len);
        if (pkt_len < sizeof(tdma_header_t) + sizeof(msg_data_hdr_t) ||
            pkt_len > 4096) {
            printf("[TCP-RX] pkt_len invalido=%u — a fechar\n", pkt_len);
            pthread_mutex_lock(&node->tcp_mutex);
            if (node->tcp_sockfd[peer_id] == tcp_fd) {
                close(tcp_fd);
                node->tcp_sockfd[peer_id] = -1;
            }
            pthread_mutex_unlock(&node->tcp_mutex);
            usleep(500000);
            continue;
        }

        /* Lê pacote completo */
        ssize_t nr = recv(tcp_fd, buffer, pkt_len, MSG_WAITALL);
        if (nr != (ssize_t)pkt_len) {
            printf("[TCP-RX] Pacote incompleto esperado=%u recebido=%zd\n", pkt_len, nr);
            pthread_mutex_lock(&node->tcp_mutex);
            if (node->tcp_sockfd[peer_id] == tcp_fd) {
                close(tcp_fd);
                node->tcp_sockfd[peer_id] = -1;
            }
            pthread_mutex_unlock(&node->tcp_mutex);
            usleep(500000);
            continue;
        }

        tdma_header_t  *hdr  = (tdma_header_t *)buffer;
        msg_data_hdr_t *data = (msg_data_hdr_t *)(buffer + sizeof(tdma_header_t));

        if (hdr->type != MSG_DATA) continue;

        uint16_t ip_len = data->data_len;
        if (ip_len == 0 || ip_len > 1500) {
            printf("[TCP-RX] ip_len invalido=%u\n", ip_len);
            continue;
        }

        pdr_update(data->src_id, data->msg_id);
        uint8_t *ip_pkt = data->payload;

        if (data->dst_id == node->node_id) {
            printf("[TCP-RX] MSG_DATA ENTREGUE src=%d dst=%d msg_id=%u %u bytes\n",
                   data->src_id, data->dst_id, data->msg_id, ip_len);
            if (node->tun_fd >= 0)
                tun_write(node->tun_fd, ip_pkt, ip_len);
        } else {
            /* Relay via kernel ip_forward:
             * injector o pacote IP na TUN — o kernel consulta a rota /32
             * adicionada pelo routing_manager (gateway = TUN IP do next_hop)
             * e faz o forwarding automático de volta para a TUN.
             * O tun_reader apanha e envia via tcp_sockfd[next_hop]. */
            printf("[TCP-RX] RELAY src=%d dst=%d\n", data->src_id, data->dst_id);
            if (node->tun_fd >= 0)
                tun_write(node->tun_fd, ip_pkt, ip_len);
        }
    }

    printf("[TCP-RX] Thread para peer %d terminada\n", peer_id);
    return NULL;
}

// ═══════════════════════════════════════════════════════════════
// THREAD TUN
// ═══════════════════════════════════════════════════════════════

void* tun_reader_loop(void *arg) {
    node_t *node = (node_t *)arg;
    uint8_t buf[TUN_MTU + 4];

    printf("[TUN] Thread iniciada (fd=%d)\n", node->tun_fd);

    if (node->tun_fd >= 0) {
        int flags = fcntl(node->tun_fd, F_GETFL, 0);
        fcntl(node->tun_fd, F_SETFL, flags & ~O_NONBLOCK);
    }

    while (node->running && g_running) {
        if (node->tun_fd >= 0) {
            ssize_t n = tun_read(node->tun_fd, buf, sizeof(buf));
            if (n > 0) {
                uint8_t dst_id = tun_get_dst_node(buf, (size_t)n);
                if (dst_id != 0 && dst_id != node->node_id) {
                    tx_queue_push(node->tx_queue, buf, (size_t)n, dst_id);
                    printf("[TUN] Pacote: %zd bytes  dst=%d  queue=%d\n",
                           n, dst_id, tx_queue_size(node->tx_queue));
                }
            }
        }
    }

    printf("[TUN] Thread terminada\n");
    return NULL;
}

// ═══════════════════════════════════════════════════════════════
// THREAD RX UDP — apenas para MATRIX
// ═══════════════════════════════════════════════════════════════

void* receiver_loop(void *arg) {
    node_t *node = (node_t *)arg;
    uint8_t buffer[2048];
    struct sockaddr_in src;
    socklen_t len = sizeof(src);
    uint16_t rp_ms = round_period_ms(node->num_nodes);

    printf("[RX] Thread iniciada, porta %d\n", node->port);

    while (node->running && g_running) {
        ssize_t n = recvfrom(node->sockfd, buffer, sizeof(buffer), 0,
                             (struct sockaddr *)&src, &len);
        if (n <= 0) continue;

        tdma_header_t *hdr = (tdma_header_t *)buffer;

        if (hdr->type == MATRIX) {
            /* regista frame atual para slot miss detection */
            if (hdr->slot_id <= MAX_NODES) {
                uint64_t now_us    = get_time_us();
                uint64_t round_us  = (uint64_t)rp_ms * 1000;
                g_last_rx_frame[hdr->slot_id] = now_us / round_us;
            }

#ifdef RELAY_METHOD_ARP
            mac_table_update(hdr->slot_id);
#endif
            sync_record_delay(hdr->slot_id, hdr->timestamp,
                              hdr->slot_begin_ms, hdr->slot_end_ms, rp_ms);

            int quality = wifi_quality_get(hdr->slot_id);
            if (quality > 0)
                MATRIX_setLinkQuality(hdr->slot_id, (uint8_t)quality);

            MATRIX_parsePkt(buffer, n, hdr->slot_id);
            printf("[RX] MATRIX de Node %d (%zd bytes)  slot=[%u,%u]\n",
                   hdr->slot_id, n, hdr->slot_begin_ms, hdr->slot_end_ms);

        } else if (hdr->type == MSG_DATA) {
            if ((size_t)n < sizeof(tdma_header_t) + sizeof(msg_data_hdr_t))
                continue;

            msg_data_hdr_t *data = (msg_data_hdr_t *)(buffer + sizeof(tdma_header_t));
            pdr_update(data->src_id, data->msg_id);

            uint8_t  *ip_pkt = data->payload;
            uint16_t  ip_len = data->data_len;

            if (ip_len == 0 || ip_len > 1500) continue;

            if (data->dst_id == node->node_id) {
                printf("[RX] MSG_DATA ENTREGUE  src=%d dst=%d msg_id=%u  %u bytes IP\n",
                       data->src_id, data->dst_id, data->msg_id, ip_len);
                if (node->tun_fd >= 0)
                    tun_write(node->tun_fd, ip_pkt, ip_len);
            } else {
                printf("[RX] RELAY  src=%d dst=%d\n", data->src_id, data->dst_id);
                if (node->tun_fd >= 0)
                    tun_write(node->tun_fd, ip_pkt, ip_len);
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
    uint8_t  pkt_buffer[4096];
    uint32_t tx_counter  = 0;
    uint16_t data_msg_id = 0;
    uint16_t rp_ms       = round_period_ms(node->num_nodes);

    struct sockaddr_in dest = {0};
    dest.sin_family = AF_INET;

    printf("[TX] Thread iniciada, Slot %d  frame=%u ms  slot=%u ms  guard=%u ms\n",
           node->node_id, rp_ms, SLOT_DURATION_US/1000, GUARD_US/1000);

    uint64_t last_round  = 0;
    uint64_t start_time  = get_time_us();
    #define STARTUP_GRACE_US  10000000ULL  /* 10s sem slot miss detection */

    /* contador de misses consecutivos por nó */
    uint8_t consecutive_miss[MAX_NODES + 1] = {0};
    #define MISS_THRESHOLD 5   /* misses consecutivos antes de degradar qualidade */

    while (node->running && g_running) {
        uint64_t now           = get_time_us();
        uint64_t time_in_frame = now % node->frame_duration_us;
        int      current_slot  = (int)(time_in_frame / SLOT_DURATION_US);

        if (current_slot != (node->node_id - 1)) {
            uint64_t round_us  = (uint64_t)rp_ms * 1000;
            uint64_t cur_round = now / round_us;
            if (cur_round != last_round) {
                last_round = cur_round;
                sync_adjust_slot(rp_ms);

                /* verifica slot misses consecutivos (só após grace period) */
                if (get_time_us() - start_time < STARTUP_GRACE_US) goto skip_miss;
                for (int s = 0; s < node->num_nodes; s++) {
                    uint8_t nid = (uint8_t)(s + 1);
                    if (nid == node->node_id) continue;
                    /* só conta miss se o nó já foi visto pelo menos uma vez */
                    if (g_last_rx_frame[nid] == 0) continue;
                    if (g_last_rx_frame[nid] < cur_round - 1) {
                        consecutive_miss[nid]++;
                        if (consecutive_miss[nid] >= MISS_THRESHOLD) {
                            MATRIX_updateLinkQuality(nid, true);
                            printf("[SLOT] Node %d: %d misses consecutivos — degradar qualidade\n",
                                   nid, consecutive_miss[nid]);
                        }
                    } else {
                        consecutive_miss[nid] = 0;  /* reset ao receber */
                    }
                }
                skip_miss:;
            }
            usleep(2000);
            continue;
        }

        uint64_t slot_start_us = now;
        (void)slot_start_us;
        /* BUG 5 FIX: removeDeadLinks() era chamado aqui E dentro de
         * serializeMatrix(), causando dupla remoção por slot.
         * serializeMatrix() já trata disto internamente. */
        uint64_t slot_end = (now - time_in_frame) +
                            ((uint64_t)(current_slot + 1) * SLOT_DURATION_US)
                            - GUARD_US;

        /* MATRIX broadcast via UDP */
        int payload_len = 0;
        void *matrix_payload = serializeMatrix(&payload_len);
        if (matrix_payload) {

            slot_limits_t sl   = sync_get_slot();
            tdma_header_t *hdr = (tdma_header_t *)pkt_buffer;
            hdr->type          = MATRIX;
            hdr->slot_id       = node->node_id;
            hdr->seq_num       = tx_counter++;
            hdr->timestamp     = (double)now / 1000000.0;
            hdr->slot_begin_ms = sl.begin_ms;
            hdr->slot_end_ms   = sl.end_ms;

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
            printf("[TX] Slot %d: MATRIX (%d bytes seq=%u)  [%u-%u ms]\n",
                   current_slot, total_len, tx_counter - 1,
                   sl.begin_ms, sl.end_ms);
            MATRIX_print();
        }

        /* MSG_DATA via TCP — sem framing extra */
        uint32_t pkts_sent  = 0;
        uint64_t bytes_sent = 0;
        tx_pkt_t *pkt;

        while ((pkt = tx_queue_pop(node->tx_queue)) != NULL) {
            if (get_time_us() >= slot_end) {
                tx_queue_push(node->tx_queue, pkt->data, pkt->len, pkt->dst_id);
                free(pkt);
                break;
            }

            uint8_t next_hop = routing_manager_lookup(node->routing, pkt->dst_id);
            if (next_hop == 0) {
                printf("[TX] Sem rota para Node %d, descartado\n", pkt->dst_id);
                free(pkt);
                continue;
            }

            tdma_header_t  *hdr  = (tdma_header_t *)pkt_buffer;
            msg_data_hdr_t *data = (msg_data_hdr_t *)(pkt_buffer + sizeof(tdma_header_t));

            hdr->type          = MSG_DATA;
            hdr->slot_id       = node->node_id;
            hdr->seq_num       = tx_counter++;
            hdr->timestamp     = (double)get_time_us() / 1000000.0;
            hdr->slot_begin_ms = 0;
            hdr->slot_end_ms   = 0;

            data->src_id   = node->node_id;
            data->dst_id   = pkt->dst_id;
            data->msg_id   = data_msg_id++;
            data->data_len = (uint16_t)pkt->len;

            if (bytes_sent + sizeof(tdma_header_t) + sizeof(msg_data_hdr_t) + pkt->len > MAX_BYTES_SLOT) {
                tx_queue_push(node->tx_queue, pkt->data, pkt->len, pkt->dst_id);
                free(pkt);
                break;
            }

            memcpy(data->payload, pkt->data, pkt->len);
            data->data_len = (uint16_t)pkt->len;
            int total_len = sizeof(tdma_header_t) + sizeof(msg_data_hdr_t) + data->data_len;
            free(pkt);

            const char *next_hop_ip = node->peer_ips[next_hop];
            if (next_hop_ip[0] == '\0') {
                printf("[TX] IP desconhecido para next_hop=%d\n", next_hop);
                continue;
            }

            /* Envia com framing: [4 bytes tamanho][pacote] */
            uint32_t net_len = htonl((uint32_t)total_len);
            uint8_t  frame[4 + 4096];
            memcpy(frame, &net_len, 4);
            memcpy(frame + 4, pkt_buffer, total_len);
            int frame_len = 4 + total_len;

            pthread_mutex_lock(&node->tcp_mutex);
            int tcp_fd = node->tcp_sockfd[next_hop];
            pthread_mutex_unlock(&node->tcp_mutex);

            ssize_t sent = -1;
            if (tcp_fd >= 0) {
                sent = send(tcp_fd, frame, frame_len, MSG_NOSIGNAL);
                if (sent < 0) {
                    printf("[TX] TCP peer %d falhou — a reconectar...\n", next_hop);
                    pthread_mutex_lock(&node->tcp_mutex);
                    if (node->tcp_sockfd[next_hop] == tcp_fd) {
                        close(tcp_fd);
                        node->tcp_sockfd[next_hop] = -1;
                    }
                    pthread_mutex_unlock(&node->tcp_mutex);
                    /* Descarta pacote — keepalive vai reconectar */
                    printf("[TX] Pacote descartado — sem ligacao TCP para peer %d\n", next_hop);
                }
            } else {
                /* Sem ligacao TCP — descarta e keepalive vai reconectar */
                printf("[TX] Sem TCP para peer %d — pacote descartado\n", next_hop);
            }

            printf("[TX] MSG_DATA  dst=%d  next_hop=%d(%s)  msg_id=%u  ip_len=%u  sent=%zd\n",
                   data->dst_id, next_hop, next_hop_ip, data->msg_id, data->data_len, sent);
            if (sent > 0) { pkts_sent++; bytes_sent += (uint64_t)sent; }
        }

        float slot_use_pct    = (float)bytes_sent / (float)MAX_BYTES_SLOT * 100.0f;
        float throughput_kbps = (bytes_sent * 8.0f * 1000000.0f) / ((float)SLOT_DURATION_US * 1000.0f);
        double t_used_us      = (bytes_sent * 8.0 * 1000000.0) / (double)WIFI_BPS;

        printf("[SLOT] Uso: %.1f%% (%.1fKB / %.1fKB)  pkts=%u  throughput=%.0fkbps"
               "  T_trans_est=%.0fus / %uus util  guard=%u ms\n",
               slot_use_pct > 100.0f ? 100.0f : slot_use_pct,
               bytes_sent / 1024.0, MAX_BYTES_SLOT / 1024.0,
               pkts_sent, throughput_kbps, t_used_us, SLOT_USEFUL_US, GUARD_US / 1000);

        int qsize = tx_queue_size(node->tx_queue);
        if (qsize > 10)
            printf("[SLOT] AVISO: fila tx_queue=%d pacotes — lag a acumular!\n", qsize);

        uint64_t now2 = get_time_us();
        if (now2 < slot_end + GUARD_US) {
            uint64_t sleep_time = slot_end + GUARD_US - now2;
            if (sleep_time < SLOT_DURATION_US)
                usleep((useconds_t)sleep_time);
        }
    }

    printf("[TX] Thread terminada\n");
    return NULL;
}

// ═══════════════════════════════════════════════════════════════
// NODE INIT / RUN / DESTROY
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
    printf("║  RA-TDMAs+  Node %d  (%s)  ║\n", node_id, tun_get_relay_method());
    printf("╚════════════════════════════════════════════════════════╝\n");
    printf("[Node %d] Porta=%d  Slot=%d  Frame=%.1fms  Slot=%ums  Guard=%ums\n\n",
           node_id, node->port, node_id - 1,
           node->frame_duration_us / 1000.0,
           SLOT_DURATION_US / 1000, GUARD_US / 1000);

    node->sockfd = socket(AF_INET, SOCK_DGRAM, 0);
    if (node->sockfd < 0) { perror("socket"); free(node); return NULL; }

    int reuse = 1;
    setsockopt(node->sockfd, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
    int broadcast = 1;
    setsockopt(node->sockfd, SOL_SOCKET, SO_BROADCAST, &broadcast, sizeof(broadcast));

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

    for (int i = 0; i <= MAX_NODES; i++)
        node->tcp_sockfd[i] = -1;
    pthread_mutex_init(&node->tcp_mutex, NULL);

    node->tcp_server_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (node->tcp_server_fd >= 0) {
        int opt = 1;
        setsockopt(node->tcp_server_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
        struct sockaddr_in tcp_addr = {0};
        tcp_addr.sin_family      = AF_INET;
        tcp_addr.sin_port        = htons(BASE_TCP_PORT + node_id);
        tcp_addr.sin_addr.s_addr = INADDR_ANY;
        if (bind(node->tcp_server_fd, (struct sockaddr *)&tcp_addr, sizeof(tcp_addr)) < 0) {
            perror("[TCP] bind"); close(node->tcp_server_fd); node->tcp_server_fd = -1;
        } else {
            listen(node->tcp_server_fd, 10);
            printf("[TCP] Server na porta %d\n", BASE_TCP_PORT + node_id);
        }
    }

    MATRIX_init(node_id);
    node->routing     = routing_manager_create(node_id, num_nodes);
    node->event_queue = event_queue_create();
    node->tx_queue    = tx_queue_create();
    g_event_queue     = node->event_queue;

#ifndef RELAY_METHOD_ARP
    if (ip_forward_enable() != 0)
        fprintf(stderr, "[Node %d] AVISO: ip_forward nao activado\n", node_id);
#endif

#ifdef RELAY_METHOD_ARP
    mac_table_init();
    printf("[Node %d] MAC table inicializada\n", node_id);
#endif

    pdr_init();
    sync_init(node_id, num_nodes, (uint16_t)(node->frame_duration_us / 1000));
    wifi_quality_start();

    node->tun_fd = tun_open(node_id);
    if (node->tun_fd < 0)
        fprintf(stderr, "[Node %d] ERRO: nao foi possivel abrir TUN\n", node_id);

    return node;
}

/* ═══════════════════════════════════════════════════════════════
 * VIDEO FEEDBACK — Nó 1 escuta porta 9002
 * Base Station envia "video_poor" quando video falha.
 * Força qualidade do link para Nó 3 a zero imediatamente.
 * ═══════════════════════════════════════════════════════════════ */
/* flag global: quando 1, suprime os +3 dos beacons para o peer em causa */
volatile int g_video_poor_active = 0;

#define VIDEO_FEEDBACK_PORT  9002
#define VIDEO_FEEDBACK_PEER  3        /* Nó 3 = base station */
#define POOR_RECOVERY_US     15000000ULL  /* 15s sem feedback antes de recuperar */

void* video_feedback_loop(void *arg) {
    node_t *node = (node_t *)arg;

    if (node->node_id != 1) return NULL;

    int sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (sock < 0) { perror("[VFEED] socket"); return NULL; }

    int opt = 1;
    setsockopt(sock, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    struct sockaddr_in addr = {0};
    addr.sin_family      = AF_INET;
    addr.sin_port        = htons(VIDEO_FEEDBACK_PORT);
    addr.sin_addr.s_addr = INADDR_ANY;
    if (bind(sock, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("[VFEED] bind"); close(sock); return NULL;
    }

    /* timeout curto para verificar POOR_RECOVERY_US com precisão */
    struct timeval tv = {1, 0};
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

    printf("[VFEED] A escutar feedback de video na porta %d\n", VIDEO_FEEDBACK_PORT);

    uint64_t last_feedback_us = 0;

    while (node->running && g_running) {
        char buf[256];
        ssize_t n = recv(sock, buf, sizeof(buf) - 1, 0);

        if (n > 0) {
            buf[n] = '\0';
            if (strstr(buf, "video_poor")) {
                last_feedback_us = get_time_us();
                g_video_poor_active = 1;
                MATRIX_setLinkQuality(VIDEO_FEEDBACK_PEER, 0);
                printf("[VFEED] Video falhou — qualidade No %d = 0\n",
                       VIDEO_FEEDBACK_PEER);
            }
        }

        /* recupera só após POOR_RECOVERY_US sem nenhum feedback */
        if (g_video_poor_active && last_feedback_us > 0) {
            uint64_t elapsed = get_time_us() - last_feedback_us;
            if (elapsed >= POOR_RECOVERY_US) {
                g_video_poor_active = 0;
                MATRIX_setLinkQuality(VIDEO_FEEDBACK_PEER, 80);
                printf("[VFEED] %lus sem feedback — link No %d recuperado\n",
                       (unsigned long)(elapsed / 1000000), VIDEO_FEEDBACK_PEER);
            } else {
                /* mantém qualidade a zero enquanto em modo poor */
                MATRIX_setLinkQuality(VIDEO_FEEDBACK_PEER, 0);
            }
        }
    }

    close(sock);
    return NULL;
}

void node_run(node_t *node) {
    signal(SIGINT, signal_handler);
    printf("[Node %d] Iniciando threads...\n\n", node->node_id);

    pthread_create(&node->receiver_thread,  NULL, receiver_loop,      node);
    pthread_create(&node->tx_thread,        NULL, tx_loop,            node);
    pthread_create(&node->event_thread,     NULL, event_handler_loop, node);

    if (node->tcp_server_fd >= 0)
        pthread_create(&node->tcp_accept_thread, NULL, tcp_accept_loop, node);

    pthread_t tcp_keepalive_thread;
    pthread_create(&tcp_keepalive_thread, NULL, tcp_keepalive_loop, node);

    if (node->tun_fd >= 0)
        pthread_create(&node->tun_thread, NULL, tun_reader_loop, node);
    else
        printf("[Node %d] AVISO: Thread TUN nao iniciada\n", node->node_id);

    pthread_t video_fb_thread;
    pthread_create(&video_fb_thread, NULL, video_feedback_loop, node);

    pthread_t tcp_rx_threads[MAX_NODES + 1];
    memset(tcp_rx_threads, 0, sizeof(tcp_rx_threads));
    for (int i = 1; i <= node->num_nodes; i++) {
        if (i == node->node_id) continue;
        tcp_rx_arg_t *arg = malloc(sizeof(tcp_rx_arg_t));
        arg->node    = node;
        arg->peer_id = i;
        pthread_create(&tcp_rx_threads[i], NULL, tcp_rx_peer_loop, arg);
    }

    pthread_join(node->receiver_thread, NULL);
    pthread_join(node->tx_thread,       NULL);
    pthread_join(node->event_thread,    NULL);
    if (node->tun_fd >= 0)
        pthread_join(node->tun_thread,  NULL);
    for (int i = 1; i <= node->num_nodes; i++) {
        if (i == node->node_id) continue;
        if (tcp_rx_threads[i])
            pthread_join(tcp_rx_threads[i], NULL);
    }
    pthread_join(tcp_keepalive_thread, NULL);

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

    wifi_quality_stop();

    pthread_mutex_lock(&node->tcp_mutex);
    for (int i = 0; i <= MAX_NODES; i++)
        if (node->tcp_sockfd[i] >= 0) close(node->tcp_sockfd[i]);
    if (node->tcp_server_fd >= 0) close(node->tcp_server_fd);
    pthread_mutex_unlock(&node->tcp_mutex);
    pthread_mutex_destroy(&node->tcp_mutex);

    if (node->tun_fd >= 0) tun_close(node->tun_fd, node->node_id);
    if (node->routing)     routing_manager_destroy(node->routing);
    if (node->event_queue) event_queue_destroy(node->event_queue);
    if (node->tx_queue)    tx_queue_destroy(node->tx_queue);

    close(node->sockfd);
    free(node);
    printf("[Node %d] Destruido\n", id);
}