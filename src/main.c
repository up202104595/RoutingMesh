/*
 * ═══════════════════════════════════════════════════════════════
 * main.c - Programa Principal
 * ═══════════════════════════════════════════════════════════════
 */

#include "node.h"
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char* argv[]) {
    if (argc != 3) {
        printf("Uso: %s <node_id> <num_nodes>\n", argv[0]);
        printf("Exemplo: %s 1 3\n", argv[0]);
        return 1;
    }
    
    int node_id = atoi(argv[1]);
    int num_nodes = atoi(argv[2]);
    
    if (node_id < 1 || node_id > MAX_NODES) {
        printf("ERRO: node_id deve estar entre 1 e %d\n", MAX_NODES);
        return 1;
    }
    
    if (num_nodes < 2 || num_nodes > MAX_NODES) {
        printf("ERRO: num_nodes deve estar entre 2 e %d\n", MAX_NODES);
        return 1;
    }
    
    if (node_id > num_nodes) {
        printf("ERRO: node_id (%d) não pode ser maior que num_nodes (%d)\n", 
               node_id, num_nodes);
        return 1;
    }
    
    // Criar e executar nó
    node_t* node = node_init(node_id, num_nodes);
    if (!node) {
        printf("ERRO: Falha ao inicializar Node %d\n", node_id);
        return 1;
    }
    
    node_run(node);
    
    node_destroy(node);
    
    return 0;
}