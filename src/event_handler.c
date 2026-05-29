/*
 * event_handler.c - Event Handler Thread
 *
 * EVENT_TOPOLOGY_CHANGED: recalcula routing apenas
 * EVENT_NODE_TIMEOUT:     fecha stream TCP (limpa buffers) — so se streaming activo
 * EVENT_NODE_JOINED:      nenhuma accao no stream
 *
 * O stream e gerido exclusivamente pelo alphabot_node.py.
 * O event_handler so fecha o ffmpeg quando um no morre —
 * o watchdog do alphabot_node.py trata do reinicio.
 */

#include "event_handler.h"
#include "routing.h"
#include "matrix.h"
#include "node.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

// ═══════════════════════════════════════════════════════════════
// EVENT QUEUE
// ═══════════════════════════════════════════════════════════════

event_queue_t* event_queue_create(void) {
    event_queue_t *queue = calloc(1, sizeof(event_queue_t));
    if (!queue) return NULL;
    queue->head    = NULL;
    queue->tail    = NULL;
    queue->count   = 0;
    queue->running = true;
    pthread_mutex_init(&queue->lock,      NULL);
    pthread_cond_init (&queue->not_empty, NULL);
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
    pthread_cond_destroy (&queue->not_empty);
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
    while (queue->head == NULL && queue->running)
        pthread_cond_wait(&queue->not_empty, &queue->lock);
    if (!queue->running) {
        pthread_mutex_unlock(&queue->lock);
        return NULL;
    }
    event_t *evt  = queue->head;
    queue->head   = evt->next;
    if (queue->head == NULL)
        queue->tail = NULL;
    queue->count--;
    pthread_mutex_unlock(&queue->lock);
    return evt;
}

// ═══════════════════════════════════════════════════════════════
// EVENT HANDLER THREAD
// ═══════════════════════════════════════════════════════════════

void* event_handler_loop(void *arg) {
    node_t *node = (node_t *)arg;

    printf("[EVENT] Thread iniciada\n");

    while (node->running) {

        event_t *evt = event_queue_pop(node->event_queue);
        if (!evt) break;

        switch (evt->type) {

            case EVENT_TOPOLOGY_CHANGED: {
                printf("\n[EVENT] Topologia mudou — recalculando routing...\n");

                matrix_snapshot_t snap;
                MATRIX_get_snapshot(&snap);

                routing_manager_recompute(
                    node->routing,
                    snap.mst_ptrs,
                    snap.link_quality,
                    snap.idOfActiveNodes,
                    snap.numberOfActiveNodes
                );

                routing_manager_print(node->routing);
                printf("[EVENT] Routing actualizado\n");

                /* Reconecta TCP imediatamente para o nó que voltou a ser
                 * alcançável. Sem isto, tcp_sockfd[peer]=-1 até o keepalive
                 * acordar (até 5s), descartando pacotes mesmo com rota directa. */
                if (evt->node_id >= 1 && evt->node_id <= node->num_nodes) {
                    pthread_mutex_lock(&node->tcp_mutex);
                    bool needs = (node->tcp_sockfd[evt->node_id] < 0);
                    pthread_mutex_unlock(&node->tcp_mutex);
                    if (needs) {
                        printf("[EVENT] TCP peer %d desconectado — a reconectar...\n",
                               evt->node_id);
                        node_tcp_reconnect(node, evt->node_id);
                    }
                }
                break;
            }

            case EVENT_NODE_TIMEOUT: {
                printf("\n[EVENT] Node %d timeout — recalculando routing...\n",
                       evt->node_id);

                matrix_snapshot_t snap;
                MATRIX_get_snapshot(&snap);

                routing_manager_recompute(
                    node->routing,
                    snap.mst_ptrs,
                    snap.link_quality,
                    snap.idOfActiveNodes,
                    snap.numberOfActiveNodes
                );

                routing_manager_print(node->routing);

                /* BUG TCP: fechar socket sem tcp_mutex causava race com
                 * tcp_rx_peer_loop e tcp_keepalive_loop */
                if (evt->node_id >= 1 && evt->node_id <= node->num_nodes) {
                    pthread_mutex_lock(&node->tcp_mutex);
                    int fd = node->tcp_sockfd[evt->node_id];
                    if (fd >= 0) {
                        close(fd);
                        node->tcp_sockfd[evt->node_id] = -1;
                        printf("[EVENT] TCP peer %d fechado — vai reconectar via relay\n", evt->node_id);
                    }
                    pthread_mutex_unlock(&node->tcp_mutex);
                }

                system("pkill -f ffplay 2>/dev/null");
                printf("[EVENT] ffplay reiniciado — buffers TCP limpos\n");
                break;
            }

            case EVENT_NODE_JOINED: {
                printf("[EVENT] Node %d entrou — recalculando routing...\n",
                       evt->node_id);

                matrix_snapshot_t snap;
                MATRIX_get_snapshot(&snap);

                routing_manager_recompute(
                    node->routing,
                    snap.mst_ptrs,
                    snap.link_quality,
                    snap.idOfActiveNodes,
                    snap.numberOfActiveNodes
                );

                routing_manager_print(node->routing);
                break;
            }
        }

        free(evt);
    }

    printf("[EVENT] Thread terminada\n");
    return NULL;
}