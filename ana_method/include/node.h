/*
 * node.h — Nó do framework RA-TDMAs+ (MÉTODO ANA MORAIS, opção literal)
 *
 * O framework é APENAS plano de controlo:
 *   • partilha a topologia (state packets UDP, em slots TDMA)
 *   • calcula a MST binária (Prim)
 *   • mantém a tabela ARP (id -> MAC do next-hop) via ioctl
 *
 * O DATA PLANE é o kernel Linux (ip_forward + ARP estática). O relay
 * é feito pelo kernel à Camada 2 sobre wlan0, NÃO pelo framework e
 * NÃO gated pelo slot — tal como na dissertação (3.2 / 3.2.6 / 4.4).
 */

#ifndef NODE_H
#define NODE_H

#include <stdint.h>
#include <pthread.h>
#include "routing_list.h"
#include "net_ana.h"

#define MAX_NODES 20

typedef struct node {
    uint8_t   node_id;
    uint8_t   num_nodes;
    int       port;
    int       sockfd;          /* UDP — único socket do framework */
    uint64_t  frame_duration_us;
    uint8_t   my_mac[MAC_BYTES];

    char      phy_iface[16];                  /* ex. "wlan0" */
    char      phy_prefix[24];                 /* ex. "172.20.10" */
    char      peer_ips[MAX_NODES + 1][32];    /* IPs físicos dos vizinhos */

    routing_ctx_t *routing;

    pthread_t receiver_thread;
    pthread_t tx_thread;

    volatile int running;
} node_t;

node_t* node_init(uint8_t node_id, uint8_t num_nodes);
void    node_run(node_t *node);
void    node_destroy(node_t *node);

#endif /* NODE_H */
