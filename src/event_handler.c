/*
 * ═══════════════════════════════════════════════════════════════
 * event_handler.c - Event Handler Thread (Simples)
 * ═══════════════════════════════════════════════════════════════
 */

#include "event_handler.h"
#include "routing.h"
#include "matrix.h"
#include "node.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// ═══════════════════════════════════════════════════════════════
// EVENT QUEUE IMPLEMENTATION
// ═══════════════════════════════════════════════════════════════

event_queue_t* event_queue_create(void) {
    event_queue_t *queue = calloc(1, sizeof(event_queue_t));
    if (!queue) return NULL;
    
    queue->head = NULL;
    queue->tail = NULL;
    queue->count = 0;
    queue->running = true;
    
    pthread_mutex_init(&queue->lock, NULL);
    pthread_cond_init(&queue->not_empty, NULL);
    
    printf("[EVENT] Fila de eventos criada\n");
    return queue;
}

void event_queue_destroy(event_queue_t *queue) {
    if (!queue) return;
    
    queue->running = false;
    pthread_cond_broadcast(&queue->not_empty);
    
    pthread_mutex_lock(&queue->lock);
    
    event_t *curr = queue->head;
    while (curr) {
        event_t *next = curr->next;
        free(curr);
        curr = next;
    }
    
    pthread_mutex_unlock(&queue->lock);
    
    pthread_mutex_destroy(&queue->lock);
    pthread_cond_destroy(&queue->not_empty);
    
    free(queue);
}

void event_queue_push(event_queue_t *queue, event_t *evt) {
    pthread_mutex_lock(&queue->lock);
    
    evt->next = NULL;
    
    if (queue->tail) {
        queue->tail->next = evt;
        queue->tail = evt;
    } else {
        queue->head = queue->tail = evt;
    }
    
    queue->count++;
    pthread_cond_signal(&queue->not_empty);
    
    pthread_mutex_unlock(&queue->lock);
}

event_t* event_queue_pop(event_queue_t *queue) {
    pthread_mutex_lock(&queue->lock);
    
    while (queue->head == NULL && queue->running) {
        pthread_cond_wait(&queue->not_empty, &queue->lock);
    }
    
    if (!queue->running) {
        pthread_mutex_unlock(&queue->lock);
        return NULL;
    }
    
    event_t *evt = queue->head;
    queue->head = evt->next;
    
    if (queue->head == NULL) {
        queue->tail = NULL;
    }
    
    queue->count--;
    
    pthread_mutex_unlock(&queue->lock);
    
    return evt;
}

// ═══════════════════════════════════════════════════════════════
// EVENT HANDLER THREAD
// ═══════════════════════════════════════════════════════════════

void* event_handler_loop(void* arg) {
    node_t *node = (node_t*)arg;
    
    printf("[EVENT] Thread iniciada\n");
    
    while (node->running) {
        
        event_t *evt = event_queue_pop(node->event_queue);
        
        if (!evt) break;
        
        switch (evt->type) {
            
            case EVENT_TOPOLOGY_CHANGED:
                printf("\n[EVENT] 🔄 Topologia mudou - recalculando routing...\n");
                
                tdma_matrix_t *matrix = MATRIX_get();
                uint8_t **mst = MATRIX_getSpanningTree();
                
                routing_manager_recompute(
                    node->routing,
                    mst,
                    matrix->link_quality,
                    matrix->idOfActiveNodes,
                    matrix->numberOfActiveNodes
                );
                
                routing_manager_print(node->routing);
                break;
                
            case EVENT_NODE_TIMEOUT:
                printf("[EVENT] ⏱️  Node %d timeout\n", evt->node_id);
                break;
                
            case EVENT_NODE_JOINED:
                printf("[EVENT] 🆕 Node %d entrou\n", evt->node_id);
                break;
        }
        
        free(evt);
    }
    
    printf("[EVENT] Thread terminada\n");
    return NULL;
}
