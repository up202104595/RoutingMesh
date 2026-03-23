/*
 * node.h  —  Estrutura principal do nó RA-TDMAs+
 */

#ifndef NODE_H
#define NODE_H

#include <stdint.h>
#include <pthread.h>

typedef struct routing_manager routing_manager_t;
typedef struct event_queue     event_queue_t;
typedef struct tx_queue        tx_queue_t;

#define MAX_NODES 20

typedef struct node {
    uint8_t  node_id;
    uint8_t  num_nodes;
    int      port;
    int      sockfd;
    int      tun_fd;           /* file descriptor da interface TUN */
    uint64_t frame_duration_us;

    char     peer_ips[MAX_NODES+1][32]; /* peer_ips[node_id] = "192.168.1.X" */

    pthread_t receiver_thread;
    pthread_t tx_thread;
    pthread_t event_thread;
    pthread_t tun_thread;      /* Thread TUN: lê tun0 → tx_queue */

    routing_manager_t *routing;
    event_queue_t     *event_queue;
    tx_queue_t        *tx_queue;   /* fila entre Thread TUN e Thread TX */

    int running;
} node_t;

node_t* node_init(uint8_t node_id, uint8_t num_nodes);
void    node_run(node_t *node);
void    node_destroy(node_t *node);

#endif /* NODE_H */