#ifndef MATRIX_H
#define MATRIX_H

#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <stdio.h>
#include <sys/types.h>

#define MAX_NODES 20 
#define MAX_AGE 5.0
#define MATRIX 1

// ═══════════════════════════════════════════════════════════════
// Cabeçalho TDMA
// ═══════════════════════════════════════════════════════════════
typedef struct {
    uint8_t type;
    uint8_t slot_id;
    uint32_t seq_num;
    double timestamp;
} __attribute__((packed)) tdma_header_t;

// ═══════════════════════════════════════════════════════════════
// Estrutura da Matriz (COM LINK QUALITY!)
// ═══════════════════════════════════════════════════════════════
typedef struct {
    uint8_t myId; 
    uint8_t numberOfActiveNodes;
    uint8_t idOfActiveNodes[MAX_NODES];
    uint8_t matrix[MAX_NODES][MAX_NODES];
    uint8_t link_quality[MAX_NODES][MAX_NODES];  // NOVO!
    double creationTime[MAX_NODES];
    double age[MAX_NODES];
} tdma_matrix_t;

// ═══════════════════════════════════════════════════════════════
// Funções Públicas
// ═══════════════════════════════════════════════════════════════

void MATRIX_init(uint8_t my_id);
void MATRIX_parsePkt(void* rx_tdmapkt_ptr, ssize_t num_bytes_read, uint8_t other_IP);
void MATRIX_print(void);
tdma_matrix_t* MATRIX_get(void);

// Serialização
void* serializeMatrix(tdma_matrix_t matrix);
void parameterSize(uint16_t *idOfActiveNodesSize, uint16_t *matrixSize, uint16_t *ageSize, uint8_t numberOfActiveNodes);

// MST e Link Quality (NOVO!)
void primAlgorithm_weighted(void);
uint8_t** MATRIX_getSpanningTree(void);
void MATRIX_updateLinkQuality(uint8_t node_id, bool timeout);

#endif