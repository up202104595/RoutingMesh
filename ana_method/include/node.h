/*
 * node.h — Nó do framework RA-TDMAs+ (MÉTODO ANA MORAIS)
 *
 * Transporte 100% UDP (porta BASE_PORT + node_id). NÃO há TCP no
 * framework — o TCP só existe se a APLICAÇÃO o usar, como na tese.
 * NÃO há separação MSG_DATA: os dados são pacotes IP raw relayed
 * de forma transparente (a app vê sempre o src original).
 */

#ifndef NODE_H
#define NODE_H

#include <stdint.h>
#include <pthread.h>
#include "routing_list.h"

#define MAX_NODES 20

typedef struct tx_queue     tx_queue_t;

typedef struct node {
    uint8_t   node_id;
    uint8_t   num_nodes;
    int       port;
    int       sockfd;          /* UDP — único socket do framework */
    int       tun_fd;
    uint64_t  frame_duration_us;
    uint8_t   my_mac[6];

    char      peer_ips[MAX_NODES + 1][32];   /* IPs físicos dos vizinhos */

    routing_ctx_t *routing;
    tx_queue_t    *tx_queue;

    pthread_t receiver_thread;
    pthread_t tx_thread;
    pthread_t tun_thread;

    volatile int running;
} node_t;

node_t* node_init(uint8_t node_id, uint8_t num_nodes);
void    node_run(node_t *node);
void    node_destroy(node_t *node);

#endif /* NODE_H */
