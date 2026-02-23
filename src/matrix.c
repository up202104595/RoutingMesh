#include "matrix.h"
#include "event_handler.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <inttypes.h>
#include <math.h>

// ═══════════════════════════════════════════════════════════════
// GLOBAIS
// ═══════════════════════════════════════════════════════════════

tdma_matrix_t g_myMatrix;
uint8_t **g_spanningTree;
FILE *topologyLog = NULL;

// ═══════════════════════════════════════════════════════════════
// PROTÓTIPOS INTERNOS
// ═══════════════════════════════════════════════════════════════
void removeDeadLinks(void);
void removeIdList(tdma_matrix_t *matrix, uint8_t pos);
void removeIdMatrix(tdma_matrix_t *matrix, uint8_t pos);
int8_t searchId(tdma_matrix_t *matrix, uint8_t id);
int compare(const void* a, const void* b);

// ═══════════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════════

double getEpoch(void) {
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return tv.tv_sec + tv.tv_usec / 1000000.0;
}

uint8_t getMyIP(void) {
    return g_myMatrix.myId;
}

int compare(const void* a, const void* b) {
    uint8_t int_a = * ( (uint8_t*) a );
    uint8_t int_b = * ( (uint8_t*) b );
    return (int_a - int_b);
}

int8_t searchId(tdma_matrix_t *matrix, uint8_t id){
    for(int i = 0; i < matrix->numberOfActiveNodes; i++){
        if(matrix->idOfActiveNodes[i] == id) return i;
    }
    return -1; 
}

// ═══════════════════════════════════════════════════════════════
// REMOÇÃO DE NÓS MORTOS
// ═══════════════════════════════════════════════════════════════

void removeIdList(tdma_matrix_t *matrix, uint8_t pos){
    int count = matrix->numberOfActiveNodes - pos - 1;
    if (count > 0) {
        memmove(&matrix->idOfActiveNodes[pos], &matrix->idOfActiveNodes[pos+1], count * sizeof(uint8_t));
        memmove(&matrix->age[pos], &matrix->age[pos+1], count * sizeof(double));
        memmove(&matrix->creationTime[pos], &matrix->creationTime[pos+1], count * sizeof(double));
    }
    matrix->numberOfActiveNodes--;
}

void removeIdMatrix(tdma_matrix_t *matrix, uint8_t pos){
    int rows_after = matrix->numberOfActiveNodes - pos - 1;
    if (rows_after > 0) {
        memmove(&matrix->matrix[pos], &matrix->matrix[pos+1], rows_after * sizeof(matrix->matrix[0]));
        memmove(&matrix->link_quality[pos], &matrix->link_quality[pos+1], rows_after * sizeof(matrix->link_quality[0]));
    }
    
    for(int i = 0; i < matrix->numberOfActiveNodes; i++){
        for(int j = pos; j < matrix->numberOfActiveNodes - 1; j++){
            matrix->matrix[i][j] = matrix->matrix[i][j+1];
            matrix->link_quality[i][j] = matrix->link_quality[i][j+1];
        }
        matrix->matrix[i][matrix->numberOfActiveNodes - 1] = 0;
        matrix->link_quality[i][matrix->numberOfActiveNodes - 1] = 0;
    }
}

void removeDeadLinks(void) {
    double time = getEpoch();
    double age;

    for(int i = 0; i < g_myMatrix.numberOfActiveNodes; i++){
        if(g_myMatrix.idOfActiveNodes[i] == getMyIP()) continue; 

        age = time - g_myMatrix.creationTime[i];
        
        if( age >= MAX_AGE){
            printf("\n[MATRIX] ⏱️  TIMEOUT: Nó %d expirou (Age: %.1fs). Removendo...\n", 
                   g_myMatrix.idOfActiveNodes[i], age);

            // Atualizar link quality
            MATRIX_updateLinkQuality(g_myMatrix.idOfActiveNodes[i], true);

            int8_t myPos = searchId(&g_myMatrix, getMyIP());
            if(myPos >= 0) g_myMatrix.matrix[myPos][i] = 0;
            
            removeIdMatrix(&g_myMatrix, i);
            removeIdList(&g_myMatrix, i); 

            i--;
        }
    }
}

// ═══════════════════════════════════════════════════════════════
// SERIALIZAÇÃO
// ═══════════════════════════════════════════════════════════════

void parameterSize(uint16_t *idOfActiveNodesSize, uint16_t *matrixSize, uint16_t *ageSize, uint8_t numberOfActiveNodes){
    *idOfActiveNodesSize = sizeof(uint8_t) * numberOfActiveNodes;
    *matrixSize = sizeof(uint8_t) * numberOfActiveNodes * numberOfActiveNodes;
    *ageSize = sizeof(double) * (numberOfActiveNodes + 1); 
}

void parameterPos(uint8_t *numberOfActiveNodesStart, uint8_t *matrixStart, uint8_t *ageStart, uint8_t numberActiveNodes){
    *numberOfActiveNodesStart = 1;
    *matrixStart = 1 + numberActiveNodes + 1; 
    *ageStart = 1 + 1 + numberActiveNodes + (numberActiveNodes * numberActiveNodes) + 1;
}

void * serializeMatrix(tdma_matrix_t copy_ignored){
    (void)copy_ignored; // Suprimir warning
    removeDeadLinks(); 

    tdma_matrix_t *mat = &g_myMatrix;

    uint16_t numberOfActiveNodesSize, idOfActiveNodesSize, matrixSize, ageSize;
    uint8_t idOfActiveNodesStart, matrixStart, ageStart;
    double time = getEpoch();

    for(int x = 0; x < mat->numberOfActiveNodes; x++){
        if( mat->idOfActiveNodes[x] == getMyIP() ){
            mat->age[x] = 0; 
            continue;
        }
        mat->age[x] = time - mat->creationTime[x];
    }

    numberOfActiveNodesSize = sizeof(uint8_t);
    parameterSize(&idOfActiveNodesSize, &matrixSize, &ageSize, mat->numberOfActiveNodes);
    parameterPos(&idOfActiveNodesStart, &matrixStart, &ageStart, mat->numberOfActiveNodes);

    uint16_t payloadpkt_len = numberOfActiveNodesSize + idOfActiveNodesSize + matrixSize + ageSize;
    void *payloadpkt_ptr = malloc(payloadpkt_len);
    
    if (!payloadpkt_ptr) return NULL;

    memcpy(payloadpkt_ptr, &mat->numberOfActiveNodes, numberOfActiveNodesSize);
    memcpy((char*)payloadpkt_ptr + idOfActiveNodesStart, &mat->idOfActiveNodes, idOfActiveNodesSize);
    
    for(int x = 0; x < mat->numberOfActiveNodes; x++){
        memcpy((char*)payloadpkt_ptr + matrixStart + ( mat->numberOfActiveNodes * x),
                 mat->matrix[x], mat->numberOfActiveNodes * sizeof(uint8_t));
    }
    memcpy((char*)payloadpkt_ptr + ageStart, &mat->age, ageSize);

    return payloadpkt_ptr;
}

tdma_matrix_t * deserializeMatrix(void *rx_tdmapkt_ptr){
    tdma_matrix_t *newData = (tdma_matrix_t*) malloc(sizeof(tdma_matrix_t));
    memset(newData, 0, sizeof(tdma_matrix_t));

    uint8_t idOfActiveNodesStart, matrixStart, ageStart;    
    uint16_t idOfActiveNodesSize, matrixSize, ageSize;      
    
    char *pktStart = (char*)rx_tdmapkt_ptr + sizeof(tdma_header_t);

    newData->numberOfActiveNodes = *pktStart;

    parameterPos(&idOfActiveNodesStart, &matrixStart, &ageStart, newData->numberOfActiveNodes);
    parameterSize(&idOfActiveNodesSize, &matrixSize, &ageSize, newData->numberOfActiveNodes);

    memcpy(newData->idOfActiveNodes, pktStart + idOfActiveNodesStart, idOfActiveNodesSize);
    
    for(int x = 0; x < newData->numberOfActiveNodes; x++){
        memcpy(newData->matrix[x], pktStart + matrixStart + newData->numberOfActiveNodes*x, 
                newData->numberOfActiveNodes*sizeof(uint8_t));
    }

    memcpy(newData->age, pktStart + ageStart, ageSize);

    return newData;
}

// ═══════════════════════════════════════════════════════════════
// UPDATE LOGIC
// ═══════════════════════════════════════════════════════════════

void copyLine(tdma_matrix_t *finalMatrix, tdma_matrix_t *matrixToCopy, 
                uint8_t oldLinePos, uint8_t newLinePos){
    int8_t rowPos = -1;
    for(int x = 0; x < matrixToCopy->numberOfActiveNodes; x++){  
        rowPos = searchId(finalMatrix, matrixToCopy->idOfActiveNodes[x]);
        if(rowPos == -1) break;
        finalMatrix->matrix[newLinePos][rowPos] = matrixToCopy->matrix[oldLinePos][x];
    }
}

void discoverIds(tdma_matrix_t *finalMatrix, tdma_matrix_t *matrixA, tdma_matrix_t *matrixB ) {
    memcpy(finalMatrix->idOfActiveNodes, matrixA->idOfActiveNodes, sizeof(uint8_t) * matrixA->numberOfActiveNodes);
    finalMatrix->numberOfActiveNodes = matrixA->numberOfActiveNodes;

    uint8_t alreadyExist = 0;
    for(int i = 0; i < matrixB->numberOfActiveNodes; i++){            
        alreadyExist = 0;
        for(int x = 0; x < finalMatrix->numberOfActiveNodes; x++){
            if(matrixB->idOfActiveNodes[i] == finalMatrix->idOfActiveNodes[x]){
                alreadyExist = 1;
                break;
            }
        }
        if(alreadyExist == 1) continue;
        
        finalMatrix->idOfActiveNodes[finalMatrix->numberOfActiveNodes++] = matrixB->idOfActiveNodes[i];
        printf("\n[MATRIX] 🆕 Novo Nó Descoberto: %d\n", matrixB->idOfActiveNodes[i]);
    }
    qsort( finalMatrix->idOfActiveNodes, finalMatrix->numberOfActiveNodes, sizeof(uint8_t), compare );
}

// ═══════════════════════════════════════════════════════════════
// MATRIX UPDATE - COM DETECÇÃO DE MUDANÇAS! ✅
// ═══════════════════════════════════════════════════════════════

void matrix_update( tdma_matrix_t *newMat, uint8_t other_IP) {
    // ───────────────────────────────────────────────────────────
    // 0. GUARDAR ESTADO ANTERIOR (para detectar mudanças)
    // ───────────────────────────────────────────────────────────
    
    int nodes_before = g_myMatrix.numberOfActiveNodes;
    
    // Guardar MST antiga
    uint8_t old_mst[MAX_NODES][MAX_NODES];
    for(int i = 0; i < MAX_NODES; i++) {
        memcpy(old_mst[i], g_spanningTree[i], MAX_NODES * sizeof(uint8_t));
    }
    
    // ───────────────────────────────────────────────────────────
    // 1. MERGE NORMAL (código original)
    // ───────────────────────────────────────────────────────────
    
    // Atualizar link quality
    MATRIX_updateLinkQuality(other_IP, false);
    
    tdma_matrix_t *final = (tdma_matrix_t*) malloc(sizeof(tdma_matrix_t));
    memset(final, 0, sizeof(tdma_matrix_t));
    final->myId = g_myMatrix.myId;

    discoverIds(final, &g_myMatrix, newMat);

    for(int i = 0; i < g_myMatrix.numberOfActiveNodes; i++){    
        int8_t linePos = searchId(final, g_myMatrix.idOfActiveNodes[i]);
        if(linePos == -1) break;
        copyLine(final, &g_myMatrix, i, linePos);
        final->creationTime[linePos] = g_myMatrix.creationTime[i];
        final->age[linePos] = g_myMatrix.age[i];
    }
    
    double time = getEpoch();
    
    int lines_updated = 0;
    for(int i = 0; i < newMat->numberOfActiveNodes; i++){
        if(newMat->idOfActiveNodes[i] == getMyIP() || newMat->age[i] >= MAX_AGE ) continue; 

        int8_t myPos = searchId(&g_myMatrix, newMat->idOfActiveNodes[i]);
        int8_t newPos = i;
        int8_t finalPos = searchId(final, newMat->idOfActiveNodes[i]);
        
        double newCreationTime = time - newMat->age[newPos];
        double myCreationTime = (myPos != -1) ? g_myMatrix.creationTime[myPos] : 0;

        if(myPos == -1 || myCreationTime < newCreationTime){  
            memset(final->matrix[finalPos], 0, MAX_NODES);
            copyLine(final, newMat, newPos, finalPos);   
            final->creationTime[finalPos] = newCreationTime;
            final->age[finalPos] = newMat->age[newPos];
            lines_updated++;
        }
    }

    int8_t myIpPos = searchId(final, getMyIP());
    int8_t otherIpPos = searchId(final, other_IP);

    bool new_direct_link = false;
    if(myIpPos >= 0 && otherIpPos >= 0) {
        if(final->matrix[myIpPos][otherIpPos] == 0) {
             printf("\n[MATRIX] 🔗 Ligação Direta: Nó %d conectado!\n", other_IP);
             new_direct_link = true;
        }
        final->matrix[myIpPos][otherIpPos] = 1; 
        final->creationTime[myIpPos] = time;
    }
    
    // Copiar link quality
    for(int i = 0; i < g_myMatrix.numberOfActiveNodes; i++) {
        int8_t finalPos = searchId(final, g_myMatrix.idOfActiveNodes[i]);
        if(finalPos >= 0) {
            for(int j = 0; j < g_myMatrix.numberOfActiveNodes; j++) {
                int8_t finalPosJ = searchId(final, g_myMatrix.idOfActiveNodes[j]);
                if(finalPosJ >= 0) {
                    final->link_quality[finalPos][finalPosJ] = g_myMatrix.link_quality[i][j];
                }
            }
        }
    }

    memcpy(&g_myMatrix, final, sizeof(tdma_matrix_t));
    free(final);
    
    // ───────────────────────────────────────────────────────────
    // 2. RECALCULAR MST
    // ───────────────────────────────────────────────────────────
    
    primAlgorithm_weighted();
    
    // ───────────────────────────────────────────────────────────
    // 3. DETECTAR SE HOUVE MUDANÇA REAL! ✅
    // ───────────────────────────────────────────────────────────
    
    bool topology_changed = false;
    
    // Mudou número de nós?
    if (g_myMatrix.numberOfActiveNodes != nodes_before) {
        topology_changed = true;
        printf("[MATRIX]   ⚠️  Número de nós mudou: %d → %d\n", 
               nodes_before, g_myMatrix.numberOfActiveNodes);
    }
    
    // Linhas atualizadas?
    if (lines_updated > 0) {
        topology_changed = true;
        printf("[MATRIX]   ⚠️  %d linhas atualizadas\n", lines_updated);
    }
    
    // Link direto novo?
    if (new_direct_link) {
        topology_changed = true;
    }
    
    // MST mudou?
    bool mst_changed = false;
    for(int i = 0; i < g_myMatrix.numberOfActiveNodes && !mst_changed; i++) {
        for(int j = 0; j < g_myMatrix.numberOfActiveNodes; j++) {
            if (old_mst[i][j] != g_spanningTree[i][j]) {
                mst_changed = true;
                topology_changed = true;
                printf("[MATRIX]   ⚠️  MST mudou!\n");
                break;
            }
        }
    }
    
    // ───────────────────────────────────────────────────────────
    // 4. CRIAR EVENTO SÓ SE MUDOU! ✅
    // ───────────────────────────────────────────────────────────
    
    if (topology_changed) {
        printf("[MATRIX] 🔔 TOPOLOGIA MUDOU - Criando evento para routing!\n\n");
        
        extern event_queue_t *g_event_queue;
        if (g_event_queue) {
            event_t *evt = malloc(sizeof(event_t));
            evt->type = EVENT_TOPOLOGY_CHANGED;
            evt->node_id = other_IP;
            evt->timestamp = getEpoch();
            evt->next = NULL;
            event_queue_push(g_event_queue, evt);
        }
    } else {
        printf("[MATRIX] ✓ Nenhuma mudança de topologia detectada\n\n");
    }
}

void MATRIX_parsePkt(void* rx_tdmapkt_ptr, ssize_t num_bytes_read, uint8_t other_IP ) {
    (void)num_bytes_read;
    tdma_matrix_t * newData = deserializeMatrix(rx_tdmapkt_ptr);
    matrix_update(newData, other_IP);
    free(newData);
}

void MATRIX_init(uint8_t my_id) {
    memset(&g_myMatrix, 0, sizeof(tdma_matrix_t));
    g_myMatrix.myId = my_id;
    g_myMatrix.numberOfActiveNodes = 1;
    g_myMatrix.idOfActiveNodes[0] = my_id;
    g_myMatrix.creationTime[0] = getEpoch();
    
    // Inicializar link quality
    for (int i = 0; i < MAX_NODES; i++) {
        for (int j = 0; j < MAX_NODES; j++) {
            g_myMatrix.link_quality[i][j] = 100;
        }
    }
    
    g_spanningTree = (uint8_t **) malloc(MAX_NODES * sizeof(uint8_t *));
    for(int r=0; r<MAX_NODES; r++) {
        g_spanningTree[r] = (uint8_t *) malloc(MAX_NODES * sizeof(uint8_t));
        memset(g_spanningTree[r], 0, MAX_NODES * sizeof(uint8_t));
    }
    
    printf("[MATRIX] Sistema inicializado.\n");
}

tdma_matrix_t* MATRIX_get(void) {
    return &g_myMatrix;
}

void MATRIX_print(void) {
    printf("[MATRIX] Nodes: ");
    for(int i = 0; i < g_myMatrix.numberOfActiveNodes; i++){
        printf("%d ", g_myMatrix.idOfActiveNodes[i]);
    }
    printf("\n");
    for(int i=0; i < g_myMatrix.numberOfActiveNodes; i++) {
        printf("N%d | ", g_myMatrix.idOfActiveNodes[i]);
        for(int x = 0; x < g_myMatrix.numberOfActiveNodes; x++) {
            if(i==x) printf("- ");
            else printf("%d ", g_myMatrix.matrix[i][x]);
        }
        printf(" (age: %.2f)\n", getEpoch() - g_myMatrix.creationTime[i]);
    }
    printf("\n");
}

// ═══════════════════════════════════════════════════════════════
// LINK QUALITY
// ═══════════════════════════════════════════════════════════════

void MATRIX_updateLinkQuality(uint8_t node_id, bool timeout) {
    int8_t my_idx = searchId(&g_myMatrix, getMyIP());
    int8_t node_idx = searchId(&g_myMatrix, node_id);
    
    if (my_idx == -1 || node_idx == -1) return;
    
    if (timeout) {
        if (g_myMatrix.link_quality[my_idx][node_idx] > 20) {
            g_myMatrix.link_quality[my_idx][node_idx] -= 20;
        } else {
            g_myMatrix.link_quality[my_idx][node_idx] = 0;
        }
    } else {
        if (g_myMatrix.link_quality[my_idx][node_idx] < 95) {
            g_myMatrix.link_quality[my_idx][node_idx] += 5;
        } else {
            g_myMatrix.link_quality[my_idx][node_idx] = 100;
        }
    }
}

// ═══════════════════════════════════════════════════════════════
// PRIM COM LINK QUALITY
// ═══════════════════════════════════════════════════════════════

void primAlgorithm_weighted(void) {
    int num = g_myMatrix.numberOfActiveNodes;
    
    if (num <= 1) {
        for(int i = 0; i < MAX_NODES; i++) {
            memset(g_spanningTree[i], 0, MAX_NODES * sizeof(uint8_t));
        }
        return;
    }
    
    bool in_mst[MAX_NODES] = {false};
    int parent[MAX_NODES];
    int key[MAX_NODES];
    
    for (int i = 0; i < num; i++) {
        key[i] = 999;
        parent[i] = -1;
    }
    
    key[0] = 0;
    
    for (int count = 0; count < num; count++) {
        int min_key = 999;
        int u = -1;
        
        for (int v = 0; v < num; v++) {
            if (!in_mst[v] && key[v] < min_key) {
                min_key = key[v];
                u = v;
            }
        }
        
        if (u == -1) break;
        in_mst[u] = true;
        
        for (int v = 0; v < num; v++) {
            uint8_t quality = g_myMatrix.link_quality[u][v];
            
            if (g_myMatrix.matrix[u][v] && !in_mst[v] && quality > 0) {
                int cost = 100 - quality;
                if (cost < key[v]) {
                    parent[v] = u;
                    key[v] = cost;
                }
            }
        }
    }
    
    for(int i = 0; i < MAX_NODES; i++) {
        memset(g_spanningTree[i], 0, MAX_NODES * sizeof(uint8_t));
    }
    
    for (int i = 1; i < num; i++) {
        if (parent[i] != -1) {
            g_spanningTree[parent[i]][i] = 1;
            g_spanningTree[i][parent[i]] = 1;
        }
    }
}

uint8_t** MATRIX_getSpanningTree(void) {
    return g_spanningTree;
}