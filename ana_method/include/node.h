/*
 * node.h — Nó do framework RA-TDMAs+ (MÉTODO ANA MORAIS, recriação literal)
 *
 * Fluxo de dados (Figura 3.13 da tese):
 *   • a app envia para o IP de wlan0 do destino; o iptables mangle
 *     desvia o pacote para a tun, onde o framework o lê
 *   • o framework envia-o por UDP, no slot, para o IP de wlan0 do
 *     destino final (porta 7000+dst)
 *   • os relays são feitos pelo KERNEL via ARP/ip_forward, imediatos
 *     (não gated pelo slot) — 3.2.6
 *   • no destino, o framework escreve o IP raw na tun -> entrega à app
 *
 * O framework partilha topologia, calcula a MST binária e mantém a
 * tabela ARP (id -> MAC do next-hop) via ioctl.
 */

#ifndef NODE_H
#define NODE_H

#include <stdint.h>
#include <pthread.h>
#include "routing_list.h"
#include "net_ana.h"

#define MAX_NODES 20

typedef struct tx_queue tx_queue_t;

typedef struct node {
    uint8_t   node_id;
    uint8_t   num_nodes;
    int       port;
    int       sockfd;          /* UDP — único socket do framework */
    uint64_t  frame_duration_us;
    uint8_t   my_mac[MAC_BYTES];

    int       tun_fd;                         /* tun (IP mesh das apps) */
    char      phy_iface[16];                  /* ex. "wlan0" */
    char      phy_prefix[24];                 /* físico, ex. "172.20.10" */
    char      mesh_prefix[24];                /* mesh/tun, ex. "10.0.0"  */
    char      peer_ips[MAX_NODES + 1][32];    /* IPs físicos dos vizinhos */

    routing_ctx_t *routing;
    tx_queue_t    *tx_queue;   /* fila thread TUN -> slot TDMA */

    pthread_t receiver_thread;
    pthread_t tx_thread;
    pthread_t tun_thread;

    volatile int running;
} node_t;

node_t* node_init(uint8_t node_id, uint8_t num_nodes);
void    node_run(node_t *node);
void    node_destroy(node_t *node);

#endif /* NODE_H */
