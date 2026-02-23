/*
 * ═══════════════════════════════════════════════════════════════
 * node.c - Implementação TDMA com Routing
 * ═══════════════════════════════════════════════════════════════
 */

#include "node.h"
#include "matrix.h"
#include "routing.h"
#include "event_handler.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <pthread.h>
#include <signal.h>

#define BASE_PORT 7000
#define SLOT_DURATION_US 200000

static volatile int g_running = 1;
event_queue_t *g_event_queue = NULL;

void signal_handler(int sig) {
    (void)sig;
    g_running = 0;
    printf("\n[SIGNAL] Recebido Ctrl+C, parando...\n");
}

uint64_t get_time_us(void) {
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return (uint64_t)tv.tv_sec * 1000000 + tv.tv_usec;
}

void* receiver_loop(void* arg) {
    node_t* node = (node_t*)arg;
    uint8_t buffer[2048];
    struct sockaddr_in src;
    socklen_t len = sizeof(src);

    printf("[RX] Thread iniciada, escutando porta %d\n", node->port);

    while (node->running && g_running) {
        ssize_t n = recvfrom(node->sockfd, buffer, sizeof(buffer), 0, 
                             (struct sockaddr*)&src, &len);
        
        if (n > 0) {
            tdma_header_t* hdr = (tdma_header_t*)buffer;
            
            if (hdr->type == MATRIX) {
                MATRIX_parsePkt(buffer, n, hdr->slot_id);
                
                printf("[RX] 📥 Matriz recebida de Node %d (%zd bytes)\n", 
                       hdr->slot_id, n);
            }
        }
    }
    
    printf("[RX] Thread terminada\n");
    return NULL;
}

void* tx_loop(void* arg) {
    node_t* node = (node_t*)arg;
    
    uint8_t pkt_buffer[2048]; 
    
    struct sockaddr_in dest = {0};
    dest.sin_family = AF_INET;
    dest.sin_addr.s_addr = inet_addr("127.0.0.1");

    printf("[TX] Thread iniciada, TDMA Slot %d\n", node->node_id - 1);
    
    uint32_t tx_counter = 0;

    while (node->running && g_running) {
        uint64_t now = get_time_us();
        
        uint64_t time_in_frame = now % node->frame_duration_us;
        int current_slot = time_in_frame / SLOT_DURATION_US;

        if (current_slot == (node->node_id - 1)) {
            
            void* matrix_payload = serializeMatrix(*MATRIX_get());
            if (matrix_payload) {
                
                uint16_t idSize, matSize, ageSize;
                parameterSize(&idSize, &matSize, &ageSize, 
                             MATRIX_get()->numberOfActiveNodes);
                
                int payload_len = sizeof(uint8_t) + idSize + matSize + ageSize;
                
                tdma_header_t* hdr = (tdma_header_t*)pkt_buffer;
                hdr->type = MATRIX;
                hdr->slot_id = node->node_id;
                hdr->seq_num = tx_counter++;
                hdr->timestamp = (double)now / 1000000.0;
                
                memcpy(pkt_buffer + sizeof(tdma_header_t), 
                       matrix_payload, payload_len);
                
                free(matrix_payload);
                
                int total_len = sizeof(tdma_header_t) + payload_len;

                for (int i = 1; i <= node->num_nodes; i++) {
                    if (i != node->node_id) {
                        dest.sin_port = htons(BASE_PORT + i);
                        sendto(node->sockfd, pkt_buffer, total_len, 0, 
                               (struct sockaddr*)&dest, sizeof(dest));
                    }
                }
                
                printf("\n[TX] 📤 Slot %d (Node %d): Matriz partilhada (%d bytes, seq=%u)\n", 
                       current_slot, node->node_id, total_len, tx_counter - 1);
                MATRIX_print();
            }

            uint64_t end_of_slot = (now - time_in_frame) + 
                                   ((current_slot + 1) * SLOT_DURATION_US);
            uint64_t now2 = get_time_us();
            if (now2 < end_of_slot) {
                uint64_t sleep_time = end_of_slot - now2;
                if (sleep_time > 0 && sleep_time < SLOT_DURATION_US) {
                    usleep(sleep_time);
                }
            }
            
        } else {
            usleep(2000); 
        }
    }
    
    printf("[TX] Thread terminada\n");
    return NULL;
}

node_t* node_init(uint8_t node_id, uint8_t num_nodes) {
    node_t* node = calloc(1, sizeof(node_t));
    if (!node) {
        printf("ERRO: Falha ao alocar memória\n");
        return NULL;
    }
    
    node->node_id = node_id;
    node->num_nodes = num_nodes;
    node->port = BASE_PORT + node_id;
    node->running = 1;
    
    node->frame_duration_us = num_nodes * SLOT_DURATION_US;

    printf("\n");
    printf("╔════════════════════════════════════════════════════════╗\n");
    printf("║  RoutingMeshNet - Node %d (Com Routing Layer 3)       ║\n", node_id);
    printf("╚════════════════════════════════════════════════════════╝\n");
    printf("[Node %d] Porta UDP: %d\n", node_id, node->port);
    printf("[Node %d] TDMA Slot: %d (Frame: %.1f ms)\n",
           node_id, node_id - 1, node->frame_duration_us / 1000.0);
    printf("[Node %d] Slot Duration: %.1f ms\n\n", 
           node_id, SLOT_DURATION_US / 1000.0);

    node->sockfd = socket(AF_INET, SOCK_DGRAM, 0);
    if (node->sockfd < 0) {
        perror("socket");
        free(node);
        return NULL;
    }
    
    int reuse = 1;
    setsockopt(node->sockfd, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
    
    struct sockaddr_in addr = {0};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(node->port);
    addr.sin_addr.s_addr = INADDR_ANY;
    
    if (bind(node->sockfd, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        perror("bind");
        close(node->sockfd);
        free(node);
        return NULL;
    }
    
    MATRIX_init(node_id);
    
    node->routing = routing_manager_create(node_id, num_nodes);
    node->event_queue = event_queue_create();
    g_event_queue = node->event_queue;
    
    return node;
}

void node_run(node_t* node) {
    signal(SIGINT, signal_handler);
    
    printf("[Node %d] Iniciando threads...\n\n", node->node_id);
    
    pthread_create(&node->receiver_thread, NULL, receiver_loop, node);
    pthread_create(&node->tx_thread, NULL, tx_loop, node);
    pthread_create(&node->event_thread, NULL, event_handler_loop, node);
    
    pthread_join(node->receiver_thread, NULL);  // SEM &
    pthread_join(node->tx_thread, NULL);        // SEM &
    pthread_join(node->event_thread, NULL);     // SEM &
    
    printf("\n[Node %d] Threads terminadas\n", node->node_id);
}

void node_destroy(node_t* node) {
    if (node) {
        uint8_t node_id = node->node_id;
        node->running = 0;
        
        if (node->event_queue) {
            node->event_queue->running = false;
            pthread_cond_broadcast(&node->event_queue->not_empty);
        }
        
        if (node->routing) routing_manager_destroy(node->routing);
        if (node->event_queue) event_queue_destroy(node->event_queue);
        
        close(node->sockfd);
        free(node);
        
        printf("[Node %d] Destruído\n", node_id);
    }
}
