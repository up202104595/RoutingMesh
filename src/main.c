/*
 * main.c  —  RA-TDMAs+  Entry point
 *
 * Uso:
 *   ./meshnode <node_id> <num_nodes>
 *
 * Os IPs físicos são calculados automaticamente:
 *   MESH_NET_PREFIX.node_id  (definido em compilação)
 *
 * Testes locais (default):   127.0.0.1, 127.0.0.2, 127.0.0.3
 * Produção WiFi/Raspberry:   192.168.2.1, 192.168.2.2, 192.168.2.3
 *
 * Para produção compilar com:
 *   make CFLAGS_EXTRA='-DMESH_NET_PREFIX=\"192.168.2\"'
 */

#include "node.h"
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char *argv[]) {

    if (argc != 3) {
        printf("Uso: %s <node_id> <num_nodes>\n", argv[0]);
        printf("\nExemplo (3 nos):\n");
        printf("  sudo %s 1 3\n", argv[0]);
        printf("  sudo %s 2 3\n", argv[0]);
        printf("  sudo %s 3 3\n", argv[0]);
        printf("\nPara producao WiFi, compilar com:\n");
        printf("  make MESH_NET_PREFIX=192.168.2\n");
        return 1;
    }

    int node_id   = atoi(argv[1]);
    int num_nodes = atoi(argv[2]);

    if (node_id < 1 || node_id > MAX_NODES) {
        printf("ERRO: node_id deve ser entre 1 e %d\n", MAX_NODES);
        return 1;
    }
    if (num_nodes < 2 || num_nodes > MAX_NODES) {
        printf("ERRO: num_nodes deve ser entre 2 e %d\n", MAX_NODES);
        return 1;
    }
    if (node_id > num_nodes) {
        printf("ERRO: node_id (%d) nao pode ser maior que num_nodes (%d)\n",
               node_id, num_nodes);
        return 1;
    }

    node_t *node = node_init((uint8_t)node_id, (uint8_t)num_nodes);
    if (!node) {
        printf("ERRO: falha ao inicializar node\n");
        return 1;
    }

    node_run(node);
    node_destroy(node);
    return 0;
}