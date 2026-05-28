/*
 * node.h  —  Estrutura principal do nó RA-TDMAs+
 *
 * Arquitectura de sockets:
 *   sockfd          — UDP para MATRIX broadcast (obrigatorio — nao ha TCP broadcast)
 *   tcp_sockfd[]    — TCP para MSG_DATA por peer (garante entrega)
 *   tcp_server_fd   — TCP server socket para aceitar ligacoes dos peers
 */

#ifndef NODE_H
#define NODE_H

#include <stdint.h>
#include <pthread.h>
#include <stdbool.h>

typedef struct routing_manager routing_manager_t;
typedef struct event_queue     event_queue_t;
typedef struct tx_queue        tx_queue_t;

#define MAX_NODES 20

typedef struct node {
    uint8_t  node_id;
    uint8_t  num_nodes;
    int      port;

    /* UDP — apenas para MATRIX broadcast */
    int      sockfd;

    /* TCP — MSG_DATA por peer */
    int      tcp_sockfd[MAX_NODES + 1];
    pthread_mutex_t tcp_mutex;  /* protege tcp_sockfd[] */
    int      tcp_server_fd;
    pthread_t tcp_accept_thread;

    int      tun_fd;
    uint64_t frame_duration_us;

    char     peer_ips[MAX_NODES+1][32];

    pthread_t receiver_thread;
    pthread_t tx_thread;
    pthread_t event_thread;
    pthread_t tun_thread;

    routing_manager_t *routing;
    event_queue_t     *event_queue;
    tx_queue_t        *tx_queue;

    int running;
} node_t;

node_t* node_init(uint8_t node_id, uint8_t num_nodes);
void    node_run(node_t *node);
void    node_destroy(node_t *node);

/* Reconecta socket TCP para um peer especifico
 * Chamado pelo event_handler quando no morre e volta */
void node_tcp_reconnect(node_t *node, uint8_t peer_id);

/* Stream control */
void stream_pause(void);
void stream_resume(void);

#endif /* NODE_H */