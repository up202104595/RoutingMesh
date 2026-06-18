/*
 * main.c — Entry point do framework RA-TDMAs+ (MÉTODO ANA MORAIS)
 *
 * Uso:  sudo ./meshnode_ana <node_id> <num_nodes>
 *
 * Compilar com o prefixo físico e interface da rede ad-hoc:
 *   make MESH_NET_PREFIX=192.168.2 MESH_PHY_IFACE=wlan0
 */

#include "node.h"
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char *argv[]) {
    if (argc != 3) {
        printf("Uso: %s <node_id> <num_nodes>\n", argv[0]);
        printf("Exemplo:  sudo %s 1 3\n", argv[0]);
        return 1;
    }

    int node_id   = atoi(argv[1]);
    int num_nodes = atoi(argv[2]);

    if (node_id < 1 || node_id > MAX_NODES ||
        num_nodes < 2 || num_nodes > MAX_NODES || node_id > num_nodes) {
        printf("ERRO: argumentos inválidos (1<=id<=num_nodes<=%d)\n", MAX_NODES);
        return 1;
    }

    node_t *node = node_init((uint8_t)node_id, (uint8_t)num_nodes);
    if (!node) { printf("ERRO: node_init falhou\n"); return 1; }

    node_run(node);
    node_destroy(node);
    return 0;
}
