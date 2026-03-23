/*
 * ═══════════════════════════════════════════════════════════════
 * event_handler.h - Event Handler Thread (Producer-Consumer)
 * ═══════════════════════════════════════════════════════════════
 */

#ifndef EVENT_HANDLER_H
#define EVENT_HANDLER_H

#include <stdint.h>
#include <stdbool.h>
#include <pthread.h>

// NÃO fazer forward declaration de node_t aqui!
// (já está definido em node.h que será incluído antes)

// ═══════════════════════════════════════════════════════════════
// TIPOS DE EVENTOS
// ═══════════════════════════════════════════════════════════════

typedef enum {
    EVENT_TOPOLOGY_CHANGED = 0,
    EVENT_NODE_TIMEOUT = 1,
    EVENT_NODE_JOINED = 2
} event_type_t;

// ═══════════════════════════════════════════════════════════════
// ESTRUTURA DE EVENTO
// ═══════════════════════════════════════════════════════════════

typedef struct event {
    event_type_t type;
    uint8_t node_id;
    double timestamp;
    struct event *next;
} event_t;

// ═══════════════════════════════════════════════════════════════
// FILA DE EVENTOS (Producer-Consumer)
// ═══════════════════════════════════════════════════════════════

typedef struct event_queue {
    event_t *head;
    event_t *tail;
    int count;
    pthread_mutex_t lock;
    pthread_cond_t not_empty;
    volatile bool running;
} event_queue_t;

// ═══════════════════════════════════════════════════════════════
// API PÚBLICA
// ═══════════════════════════════════════════════════════════════

// Lifecycle da fila
event_queue_t* event_queue_create(void);
void event_queue_destroy(event_queue_t *queue);

// Operações
void event_queue_push(event_queue_t *queue, event_t *evt);
event_t* event_queue_pop(event_queue_t *queue);  // Blocking

// Event Handler Thread (void* evita dependência circular)
void* event_handler_loop(void* arg);

#endif
