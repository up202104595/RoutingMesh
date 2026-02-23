/*
 * ═══════════════════════════════════════════════════════════════
 * routing.h - Routing Manager com Link Quality (MST-based)
 * 
 * Método: Como Ana Morais (linked lists da MST, SEM BFS!)
 * Contribuição: Link Quality (0-100) em vez de matriz binária
 * ═══════════════════════════════════════════════════════════════
 */

#ifndef ROUTING_H
#define ROUTING_H

#include <stdint.h>
#include <stdbool.h>
#include <pthread.h>

#define MAX_NODES 20

// ═══════════════════════════════════════════════════════════════
// ESTRUTURAS
// ═══════════════════════════════════════════════════════════════

// Estatísticas de Link (para calcular qualidade)
typedef struct {
    uint32_t packets_received;
    uint32_t packets_expected;
    uint32_t consecutive_losses;
    double last_seen;
} link_stats_t;

// Entrada na Routing Table
typedef struct {
    uint8_t destination;     // Node ID destino
    uint8_t next_hop;        // Próximo salto
    uint8_t hops;            // Número de hops
    uint8_t quality;         // Qualidade do path (0-100)
    bool valid;              // Rota válida?
} routing_entry_t;

// Routing Manager
typedef struct routing_manager {
    uint8_t my_node_id;
    uint8_t num_nodes;
    
    // Routing Table
    routing_entry_t routing_table[MAX_NODES];
    
    // Link Statistics (para link quality)
    link_stats_t link_stats[MAX_NODES];
    
    // Flags
    volatile bool needs_recompute;
    
    // Métricas
    uint32_t recompute_count;
    uint64_t last_recompute_time_us;
    
    pthread_mutex_t lock;
} routing_manager_t;

// ═══════════════════════════════════════════════════════════════
// API PÚBLICA
// ═══════════════════════════════════════════════════════════════

// Lifecycle
routing_manager_t* routing_manager_create(uint8_t my_node_id, uint8_t num_nodes);
void routing_manager_destroy(routing_manager_t *rm);

// Atualizar estatísticas de link
void routing_manager_update_link_stats(routing_manager_t *rm, 
                                       uint8_t node_id, 
                                       bool received);

// Recalcular rotas (chamado pelo Event Handler)
void routing_manager_recompute(routing_manager_t *rm, 
                               uint8_t **spanning_tree,
                               uint8_t link_quality[MAX_NODES][MAX_NODES],
                               uint8_t *active_nodes,
                               uint8_t num_active);

// Lookup de rota
uint8_t routing_manager_lookup(routing_manager_t *rm, uint8_t destination);

// Print routing table
void routing_manager_print(routing_manager_t *rm);

// Sinalizar necessidade de recomputação
void routing_manager_mark_dirty(routing_manager_t *rm);

#endif
