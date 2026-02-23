/*
 * ═══════════════════════════════════════════════════════════════
 * routing.c - Routing baseado em MST (MÉTODO DA ANA MORAIS!)
 * 
 * Método: Linked Lists diretamente da MST (SEM BFS!)
 * Contribuição: Link Quality (0-100) em vez de matriz binária
 * ═══════════════════════════════════════════════════════════════
 */

#include "routing.h"
#include "matrix.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>

// ═══════════════════════════════════════════════════════════════
// ESTRUTURA DE ROUTING (exatamente como Ana!)
// ═══════════════════════════════════════════════════════════════

typedef struct route_node {
    uint8_t node_id;              // Node ID
    uint8_t quality;              // Link quality (NOVO!)
    struct route_node *reachable; // Secondary list (nós alcançáveis via este)
    struct route_node *next;      // Next na primary list
} route_node_t;

// ═══════════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════════

static uint64_t get_time_us(void) {
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return (uint64_t)tv.tv_sec * 1000000 + tv.tv_usec;
}

static double getEpoch(void) {
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return tv.tv_sec + tv.tv_usec / 1000000.0;
}

static int8_t find_node_index(uint8_t *active_nodes, uint8_t num_active, uint8_t node_id) {
    for (int i = 0; i < num_active; i++) {
        if (active_nodes[i] == node_id) return i;
    }
    return -1;
}

// ═══════════════════════════════════════════════════════════════
// VERIFICAR SE 'target' É ALCANÇÁVEL A PARTIR DE 'start' NA MST
// (DFS simples para verificar conectividade)
// ═══════════════════════════════════════════════════════════════

static bool is_reachable_via_mst(uint8_t **mst, 
                                 uint8_t num_active,
                                 uint8_t start_idx, 
                                 uint8_t target_idx,
                                 bool *visited) {
    
    if (start_idx == target_idx) return true;
    
    visited[start_idx] = true;
    
    for (int i = 0; i < num_active; i++) {
        if (mst[start_idx][i] && !visited[i]) {
            if (is_reachable_via_mst(mst, num_active, i, target_idx, visited)) {
                return true;
            }
        }
    }
    
    return false;
}

// ═══════════════════════════════════════════════════════════════
// LIMPAR LINKED LISTS
// ═══════════════════════════════════════════════════════════════

static void free_routing_lists(route_node_t *list) {
    while (list) {
        route_node_t *next_primary = list->next;
        
        // Libera secondary list
        route_node_t *secondary = list->reachable;
        while (secondary) {
            route_node_t *next_sec = secondary->next;
            free(secondary);
            secondary = next_sec;
        }
        
        free(list);
        list = next_primary;
    }
}

// ═══════════════════════════════════════════════════════════════
// CONSTRUIR ROUTING STRUCTURE (MÉTODO DA ANA!)
// ═══════════════════════════════════════════════════════════════

static route_node_t* build_routing_structure(
    uint8_t my_node_id,
    uint8_t **mst,
    uint8_t link_quality[MAX_NODES][MAX_NODES],
    uint8_t *active_nodes,
    uint8_t num_active)
{
    route_node_t *primary_list = NULL;
    
    int8_t my_idx = find_node_index(active_nodes, num_active, my_node_id);
    if (my_idx == -1) return NULL;
    
    printf("[ROUTING] Construindo estrutura de routing...\n");
    
    // ───────────────────────────────────────────────────────────
    // 1. PERCORRE MST: ENCONTRA VIZINHOS DIRETOS (Primary List)
    // ───────────────────────────────────────────────────────────
    
    for (int i = 0; i < num_active; i++) {
        
        if (mst[my_idx][i] == 1) {  // Link direto na MST!
            
            uint8_t neighbor_id = active_nodes[i];
            uint8_t quality = link_quality[my_idx][i];
            
            printf("[ROUTING]   Vizinho direto: Node %d (quality: %d)\n", 
                   neighbor_id, quality);
            
            // Cria nó na PRIMARY list
            route_node_t *primary = malloc(sizeof(route_node_t));
            primary->node_id = neighbor_id;
            primary->quality = quality;
            primary->reachable = NULL;
            primary->next = primary_list;
            primary_list = primary;
            
            // ───────────────────────────────────────────────────
            // 2. Para ESTE vizinho: quem é alcançável VIA ele?
            // ───────────────────────────────────────────────────
            
            for (int j = 0; j < num_active; j++) {
                
                if (j == my_idx || j == i) continue;
                
                // Verifica se J é alcançável a partir de I na MST
                bool visited[MAX_NODES] = {false};
                visited[my_idx] = true;  // Não voltar por mim
                
                if (is_reachable_via_mst(mst, num_active, i, j, visited)) {
                    
                    uint8_t reachable_id = active_nodes[j];
                    
                    // Adiciona à SECONDARY list
                    route_node_t *secondary = malloc(sizeof(route_node_t));
                    secondary->node_id = reachable_id;
                    secondary->quality = 0;  // Qualidade do path completo (pode calcular)
                    secondary->next = primary->reachable;
                    primary->reachable = secondary;
                    
                    printf("[ROUTING]     → Alcançável via Node %d: Node %d\n",
                           neighbor_id, reachable_id);
                }
            }
        }
    }
    
    return primary_list;
}

// ═══════════════════════════════════════════════════════════════
// LOOKUP: ENCONTRAR NEXT HOP (MÉTODO DA ANA!)
// ═══════════════════════════════════════════════════════════════

static uint8_t lookup_next_hop(route_node_t *primary_list, uint8_t destination) {
    
    // ───────────────────────────────────────────────────────────
    // 1. PROCURA NAS SECONDARY LISTS (alcançáveis via vizinhos)
    // ───────────────────────────────────────────────────────────
    
    for (route_node_t *p = primary_list; p != NULL; p = p->next) {
        
        for (route_node_t *s = p->reachable; s != NULL; s = s->next) {
            
            if (s->node_id == destination) {
                return p->node_id;  // Next hop = vizinho que alcança destino!
            }
        }
    }
    
    // ───────────────────────────────────────────────────────────
    // 2. SE NÃO ENCONTROU: pode ser vizinho DIRETO
    // ───────────────────────────────────────────────────────────
    
    for (route_node_t *p = primary_list; p != NULL; p = p->next) {
        if (p->node_id == destination) {
            return p->node_id;  // Destino é vizinho direto!
        }
    }
    
    return 0;  // Unreachable
}

// ═══════════════════════════════════════════════════════════════
// LIFECYCLE
// ═══════════════════════════════════════════════════════════════

routing_manager_t* routing_manager_create(uint8_t my_node_id, uint8_t num_nodes) {
    routing_manager_t *rm = calloc(1, sizeof(routing_manager_t));
    if (!rm) return NULL;
    
    rm->my_node_id = my_node_id;
    rm->num_nodes = num_nodes;
    rm->needs_recompute = false;
    rm->recompute_count = 0;
    
    pthread_mutex_init(&rm->lock, NULL);
    
    printf("[ROUTING] Manager criado para Node %d\n", my_node_id);
    return rm;
}

void routing_manager_destroy(routing_manager_t *rm) {
    if (rm) {
        pthread_mutex_destroy(&rm->lock);
        free(rm);
    }
}

// ═══════════════════════════════════════════════════════════════
// LINK QUALITY TRACKING
// ═══════════════════════════════════════════════════════════════

void routing_manager_update_link_stats(routing_manager_t *rm, 
                                       uint8_t node_id, 
                                       bool received) {
    pthread_mutex_lock(&rm->lock);
    
    link_stats_t *stats = &rm->link_stats[node_id];
    
    if (received) {
        stats->packets_received++;
        stats->packets_expected++;
        stats->consecutive_losses = 0;
        stats->last_seen = getEpoch();
    } else {
        // Timeout
        stats->packets_expected++;
        stats->consecutive_losses++;
    }
    
    pthread_mutex_unlock(&rm->lock);
}

// ═══════════════════════════════════════════════════════════════
// RECOMPUTE ROUTES (chamado pelo Event Handler!)
// ═══════════════════════════════════════════════════════════════

void routing_manager_recompute(routing_manager_t *rm, 
                               uint8_t **spanning_tree,
                               uint8_t link_quality[MAX_NODES][MAX_NODES],
                               uint8_t *active_nodes,
                               uint8_t num_active) {
    
    pthread_mutex_lock(&rm->lock);
    
    uint64_t start = get_time_us();
    
    printf("\n[ROUTING] ═══════════════════════════════════════════\n");
    printf("[ROUTING] Recalculando rotas (Método Ana + Link Quality)\n");
    printf("[ROUTING] ═══════════════════════════════════════════\n");
    
    // ───────────────────────────────────────────────────────────
    // 1. CONSTRÓI LINKED LISTS DA MST (método da Ana!)
    // ───────────────────────────────────────────────────────────
    
    route_node_t *primary_list = build_routing_structure(
        rm->my_node_id,
        spanning_tree,
        link_quality,
        active_nodes,
        num_active
    );
    
    // ───────────────────────────────────────────────────────────
    // 2. PREENCHE ROUTING TABLE (lookup para cada destino)
    // ───────────────────────────────────────────────────────────
    
    memset(rm->routing_table, 0, sizeof(rm->routing_table));
    
    for (int i = 0; i < num_active; i++) {
        uint8_t dest_id = active_nodes[i];
        
        if (dest_id == rm->my_node_id) {
            rm->routing_table[i].valid = false;
            continue;
        }
        
        uint8_t next_hop = lookup_next_hop(primary_list, dest_id);
        
        if (next_hop != 0) {
            rm->routing_table[i].destination = dest_id;
            rm->routing_table[i].next_hop = next_hop;
            rm->routing_table[i].valid = true;
            
            // Qualidade (do primeiro hop)
            int8_t my_idx = find_node_index(active_nodes, num_active, rm->my_node_id);
            int8_t nh_idx = find_node_index(active_nodes, num_active, next_hop);
            
            if (my_idx != -1 && nh_idx != -1) {
                rm->routing_table[i].quality = link_quality[my_idx][nh_idx];
            }
        }
    }
    
    // Libera linked lists (já preencheu routing table)
    free_routing_lists(primary_list);
    
    uint64_t elapsed = get_time_us() - start;
    rm->last_recompute_time_us = elapsed;
    rm->recompute_count++;
    rm->needs_recompute = false;
    
    printf("[ROUTING] ✅ Rotas recalculadas em %lu µs\n", elapsed);
    printf("[ROUTING] ═══════════════════════════════════════════\n\n");
    
    pthread_mutex_unlock(&rm->lock);
}

// ═══════════════════════════════════════════════════════════════
// LOOKUP
// ═══════════════════════════════════════════════════════════════

uint8_t routing_manager_lookup(routing_manager_t *rm, uint8_t destination) {
    pthread_mutex_lock(&rm->lock);
    
    uint8_t next_hop = 0;
    
    for (int i = 0; i < rm->num_nodes; i++) {
        if (rm->routing_table[i].destination == destination && 
            rm->routing_table[i].valid) {
            next_hop = rm->routing_table[i].next_hop;
            break;
        }
    }
    
    pthread_mutex_unlock(&rm->lock);
    return next_hop;
}

// ═══════════════════════════════════════════════════════════════
// PRINT
// ═══════════════════════════════════════════════════════════════

void routing_manager_print(routing_manager_t *rm) {
    pthread_mutex_lock(&rm->lock);
    
    printf("\n╔════════════════════════════════════════════════╗\n");
    printf("║  ROUTING TABLE - Node %d                      ║\n", rm->my_node_id);
    printf("╠════════════════════════════════════════════════╣\n");
    printf("║ Dest │ Next Hop │ Quality │ Valid            ║\n");
    printf("╠══════╪══════════╪═════════╪══════════════════╣\n");
    
    bool has_routes = false;
    for (int i = 0; i < MAX_NODES; i++) {
        if (rm->routing_table[i].valid) {
            printf("║  %2d  │    %2d    │   %3d   │    ✅          ║\n",
                   rm->routing_table[i].destination,
                   rm->routing_table[i].next_hop,
                   rm->routing_table[i].quality);
            has_routes = true;
        }
    }
    
    if (!has_routes) {
        printf("║             (sem rotas)                      ║\n");
    }
    
    printf("╚════════════════════════════════════════════════╝\n\n");
    
    pthread_mutex_unlock(&rm->lock);
}

void routing_manager_mark_dirty(routing_manager_t *rm) {
    rm->needs_recompute = true;
}
