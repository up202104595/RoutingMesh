#ifndef NODE_H
#define NODE_H

#include <stdint.h>
#include <pthread.h>

// Forward declarations (evita dependência circular)
typedef struct routing_manager routing_manager_t;
typedef struct event_queue event_queue_t;

#define MAX_NODES 20

// ═══════════════════════════════════════════════════════════════
// Estrutura do Nó (COM ROUTING!)
// ═══════════════════════════════════════════════════════════════
typedef struct node {
    uint8_t node_id;
    uint8_t num_nodes;
    int port;
    int sockfd;
    uint64_t frame_duration_us;
    
    pthread_t receiver_thread;
    pthread_t tx_thread;
    pthread_t event_thread;          // NOVO!
    
    routing_manager_t *routing;      // NOVO!
    event_queue_t *event_queue;      // NOVO!
    
    int running;
} node_t;

// ═══════════════════════════════════════════════════════════════
// Funções Públicas
// ═══════════════════════════════════════════════════════════════

node_t* node_init(uint8_t node_id, uint8_t num_nodes);
void node_run(node_t* node);
void node_destroy(node_t* node);

#endif
