#include "matrix.h"
#include "event_handler.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <inttypes.h>
#include <math.h>
#include <pthread.h>

tdma_matrix_t g_myMatrix;
uint8_t **g_spanningTree;
FILE *topologyLog = NULL;

/* ── mutex recursivo: protege g_myMatrix e g_spanningTree ──
 * Recursivo porque removeDeadLinks é chamado internamente por
 * serializeMatrix, que já detém o lock. */
static pthread_mutex_t g_matrix_mutex;

void removeDeadLinks(void);
void removeIdList(tdma_matrix_t *matrix, uint8_t pos);
void removeIdMatrix(tdma_matrix_t *matrix, uint8_t pos);
int8_t searchId(tdma_matrix_t *matrix, uint8_t id);
int compare(const void* a, const void* b);

double getEpoch(void) {
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return tv.tv_sec + tv.tv_usec / 1000000.0;
}

uint8_t getMyIP(void) {
    /* myId nunca muda após init — sem lock necessário */
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

/* ── versão interna sem lock (chamada com g_matrix_mutex já detido) ── */
static void removeDeadLinks_locked(void) {
    double time = getEpoch();
    double age;
    for(int i = 0; i < g_myMatrix.numberOfActiveNodes; i++){
        if(g_myMatrix.idOfActiveNodes[i] == getMyIP()) continue;
        age = time - g_myMatrix.creationTime[i];
        if(age >= MAX_AGE){
            printf("\n[MATRIX] TIMEOUT: No %d expirou (Age: %.1fs). Removendo...\n",
                   g_myMatrix.idOfActiveNodes[i], age);
            /* penaliza link quality — sem lock extra (recursivo) */
            int8_t my_idx  = searchId(&g_myMatrix, getMyIP());
            int8_t node_idx = i; /* já é a posição */
            if(my_idx != -1 && node_idx != -1) {
                if(g_myMatrix.link_quality[my_idx][node_idx] > 20)
                    g_myMatrix.link_quality[my_idx][node_idx] -= 20;
                else
                    g_myMatrix.link_quality[my_idx][node_idx] = 0;
            }
            int8_t myPos = searchId(&g_myMatrix, getMyIP());
            if(myPos >= 0) g_myMatrix.matrix[myPos][i] = 0;
            removeIdMatrix(&g_myMatrix, i);
            removeIdList(&g_myMatrix, i);
            i--;
        }
    }
}

void removeDeadLinks(void) {
    pthread_mutex_lock(&g_matrix_mutex);
    removeDeadLinks_locked();
    pthread_mutex_unlock(&g_matrix_mutex);
}

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

/* BUG 1 (mutex) + BUG 2 (buffer overflow) corrigidos:
 *  - lock protege g_myMatrix contra escrita concorrente do RX
 *  - payloadpkt_len calculado a partir de ageStart+ageSize para
 *    cobrir os 2 bytes de gap que o parameterPos introduz */
void * serializeMatrix(int *out_payload_len){
    pthread_mutex_lock(&g_matrix_mutex);
    removeDeadLinks_locked();

    tdma_matrix_t *mat = &g_myMatrix;
    uint16_t idOfActiveNodesSize, matrixSize, ageSize;
    uint8_t  idOfActiveNodesStart, matrixStart, ageStart;
    double   time = getEpoch();

    int8_t myPos = searchId(mat, getMyIP());
    if (myPos >= 0)
        mat->creationTime[myPos] = time;

    for(int x = 0; x < mat->numberOfActiveNodes; x++){
        if(mat->idOfActiveNodes[x] == getMyIP()){
            mat->age[x] = 0;
            continue;
        }
        mat->age[x] = time - mat->creationTime[x];
    }

    parameterSize(&idOfActiveNodesSize, &matrixSize, &ageSize, mat->numberOfActiveNodes);
    parameterPos(&idOfActiveNodesStart, &matrixStart, &ageStart, mat->numberOfActiveNodes);

    /* BUG 2 FIX: o tamanho real é ageStart+ageSize, não a soma ingénua
     * que ignorava os 2 bytes de gap introduzidos por parameterPos */
    uint16_t payloadpkt_len = (uint16_t)ageStart + ageSize;

    if (out_payload_len) *out_payload_len = (int)payloadpkt_len;

    void *payloadpkt_ptr = malloc(payloadpkt_len);
    if (!payloadpkt_ptr) {
        pthread_mutex_unlock(&g_matrix_mutex);
        return NULL;
    }
    memset(payloadpkt_ptr, 0, payloadpkt_len);

    memcpy(payloadpkt_ptr, &mat->numberOfActiveNodes, sizeof(uint8_t));
    memcpy((char*)payloadpkt_ptr + idOfActiveNodesStart, &mat->idOfActiveNodes, idOfActiveNodesSize);
    for(int x = 0; x < mat->numberOfActiveNodes; x++){
        memcpy((char*)payloadpkt_ptr + matrixStart + (mat->numberOfActiveNodes * x),
               mat->matrix[x], mat->numberOfActiveNodes * sizeof(uint8_t));
    }
    memcpy((char*)payloadpkt_ptr + ageStart, &mat->age, ageSize);

    pthread_mutex_unlock(&g_matrix_mutex);
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

void copyLine(tdma_matrix_t *finalMatrix, tdma_matrix_t *matrixToCopy, 
              uint8_t oldLinePos, uint8_t newLinePos){
    int8_t rowPos = -1;
    for(int x = 0; x < matrixToCopy->numberOfActiveNodes; x++){  
        rowPos = searchId(finalMatrix, matrixToCopy->idOfActiveNodes[x]);
        if(rowPos == -1) break;
        finalMatrix->matrix[newLinePos][rowPos] = matrixToCopy->matrix[oldLinePos][x];
    }
}

void discoverIds(tdma_matrix_t *finalMatrix, tdma_matrix_t *matrixA, tdma_matrix_t *matrixB) {
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
        printf("\n[MATRIX] Novo No Descoberto: %d\n", matrixB->idOfActiveNodes[i]);
    }
    qsort(finalMatrix->idOfActiveNodes, finalMatrix->numberOfActiveNodes, sizeof(uint8_t), compare);
}

void matrix_update(tdma_matrix_t *newMat, uint8_t other_IP) {
    pthread_mutex_lock(&g_matrix_mutex);
    int nodes_before = g_myMatrix.numberOfActiveNodes;
    
    uint8_t old_mst[MAX_NODES][MAX_NODES];
    for(int i = 0; i < MAX_NODES; i++)
        memcpy(old_mst[i], g_spanningTree[i], MAX_NODES * sizeof(uint8_t));
    
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
    
    for(int i = 0; i < newMat->numberOfActiveNodes; i++){
        if(newMat->idOfActiveNodes[i] == getMyIP() || newMat->age[i] >= MAX_AGE) continue;

        bool is_direct = (newMat->idOfActiveNodes[i] == other_IP);
        int8_t myPos = searchId(&g_myMatrix, newMat->idOfActiveNodes[i]);
        int8_t finalPos = searchId(final, newMat->idOfActiveNodes[i]);

        if (!is_direct && myPos != -1) {
            double age_local = time - g_myMatrix.creationTime[myPos];
            if (age_local >= MAX_AGE) continue;
        }

        double newCreationTime = time - newMat->age[i];
        double myCreationTime = (myPos != -1) ? g_myMatrix.creationTime[myPos] : 0;
        if(myPos == -1 || myCreationTime < newCreationTime){
            memset(final->matrix[finalPos], 0, MAX_NODES);
            copyLine(final, newMat, i, finalPos);
            /* Nós indirectos NÃO refrescam creationTime local — só directos.
             * Garante que se Node 3 ficar inacessível directamente, expira
             * no Node 1 após MAX_AGE mesmo que Node 2 o reporte como vivo. */
            if(is_direct) {
                final->creationTime[finalPos] = newCreationTime;
            } else {
                final->creationTime[finalPos] = (myPos != -1) ? g_myMatrix.creationTime[myPos] : newCreationTime;
            }
            final->age[finalPos] = newMat->age[i];
        }
    }

    int8_t myIpPos = searchId(final, getMyIP());
    int8_t otherIpPos = searchId(final, other_IP);

    if(myIpPos >= 0 && otherIpPos >= 0) {
        if(final->matrix[myIpPos][otherIpPos] == 0)
            printf("\n[MATRIX] Ligacao Direta: No %d conectado!\n", other_IP);
        /* Confirmamos que NÓS ouvimos other — só actualizamos a nossa linha.
         * NÃO forçamos matrix[other][me]=1: o canal pode ser assimétrico
         * (eu ouço-o mas ele não me ouve). O Prim's usa OR para incluir
         * arestas parcialmente confirmadas. */
        final->matrix[myIpPos][otherIpPos] = 1;
        final->creationTime[myIpPos] = time;
    }

    for(int i = 0; i < g_myMatrix.numberOfActiveNodes; i++) {
        int8_t finalPos = searchId(final, g_myMatrix.idOfActiveNodes[i]);
        if(finalPos >= 0) {
            for(int j = 0; j < g_myMatrix.numberOfActiveNodes; j++) {
                int8_t finalPosJ = searchId(final, g_myMatrix.idOfActiveNodes[j]);
                if(finalPosJ >= 0)
                    final->link_quality[finalPos][finalPosJ] = g_myMatrix.link_quality[i][j];
            }
        }
    }

    for(int i = 0; i < final->numberOfActiveNodes; i++)
        for(int j = 0; j < final->numberOfActiveNodes; j++)
            if(i != j && final->matrix[i][j] == 1 && final->link_quality[i][j] == 0)
                final->link_quality[i][j] = INITIAL_LINK_QUALITY;

    /* Boost aplicado DEPOIS do copy loop e fill-zeros para não ser
     * sobrescrito. O copy loop copia g_myMatrix.link_quality[me][other]
     * (apenas 5 após MATRIX_updateLinkQuality) e anulava o boost.
     * quality[relay][other] = INITIAL_LINK_QUALITY = 50 (fill-zeros).
     * Com quality[me][other] = INITIAL+10 = 60 > 50, o Prim's escolhe
     * directo imediatamente no primeiro MATRIX directo recebido. */
    if(myIpPos >= 0 && otherIpPos >= 0) {
        if(final->link_quality[myIpPos][otherIpPos] < INITIAL_LINK_QUALITY + 10)
            final->link_quality[myIpPos][otherIpPos] = INITIAL_LINK_QUALITY + 10;
    }

    memcpy(&g_myMatrix, final, sizeof(tdma_matrix_t));
    free(final);
    
    primAlgorithm_weighted();
    
    bool topology_changed = false;
    
    if(g_myMatrix.numberOfActiveNodes != nodes_before) {
        topology_changed = true;
        printf("[MATRIX] Mudanca no numero de nos: %d -> %d\n", nodes_before, g_myMatrix.numberOfActiveNodes);
    }
    
    if(g_myMatrix.numberOfActiveNodes >= 2 && nodes_before >= 2) {
        for(int i = 0; i < g_myMatrix.numberOfActiveNodes && !topology_changed; i++) {
            for(int j = 0; j < g_myMatrix.numberOfActiveNodes; j++) {
                if(old_mst[i][j] != g_spanningTree[i][j]) {
                    topology_changed = true;
                    printf("[MATRIX] MST mudou!\n");
                    break;
                }
            }
        }
    }
    
    pthread_mutex_unlock(&g_matrix_mutex);

    /* dispara evento FORA do lock para evitar inversão de prioridade */
    if(topology_changed) {
        printf("[MATRIX] TOPOLOGIA MUDOU - Criando evento para routing!\n\n");
        extern event_queue_t *g_event_queue;
        if(g_event_queue) {
            event_t *evt = malloc(sizeof(event_t));
            evt->type = EVENT_TOPOLOGY_CHANGED;
            evt->node_id = other_IP;
            evt->timestamp = getEpoch();
            evt->next = NULL;
            event_queue_push(g_event_queue, evt);
        }
    } else {
        printf("[MATRIX] Nenhuma mudanca estrutural detectada\n\n");
    }
}

void MATRIX_parsePkt(void* rx_tdmapkt_ptr, ssize_t num_bytes_read, uint8_t other_IP) {
    (void)num_bytes_read;
    tdma_matrix_t *newData = deserializeMatrix(rx_tdmapkt_ptr);
    matrix_update(newData, other_IP);
    free(newData);
}

void MATRIX_init(uint8_t my_id) {
    pthread_mutexattr_t attr;
    pthread_mutexattr_init(&attr);
    pthread_mutexattr_settype(&attr, PTHREAD_MUTEX_RECURSIVE);
    pthread_mutex_init(&g_matrix_mutex, &attr);
    pthread_mutexattr_destroy(&attr);

    memset(&g_myMatrix, 0, sizeof(tdma_matrix_t));
    g_myMatrix.myId = my_id;
    g_myMatrix.numberOfActiveNodes = 1;
    g_myMatrix.idOfActiveNodes[0] = my_id;
    g_myMatrix.creationTime[0] = getEpoch();
    g_spanningTree = (uint8_t **) malloc(MAX_NODES * sizeof(uint8_t *));
    for(int r = 0; r < MAX_NODES; r++) {
        g_spanningTree[r] = (uint8_t *) malloc(MAX_NODES * sizeof(uint8_t));
        memset(g_spanningTree[r], 0, MAX_NODES * sizeof(uint8_t));
    }
    printf("[MATRIX] Sistema inicializado.\n");
}

tdma_matrix_t* MATRIX_get(void) {
    /* Devolve ponteiro directo — caller deve ter g_matrix_mutex
     * ou usar MATRIX_get_snapshot() para acesso thread-safe. */
    return &g_myMatrix;
}

uint8_t MATRIX_getNumNodes(void) {
    pthread_mutex_lock(&g_matrix_mutex);
    uint8_t n = g_myMatrix.numberOfActiveNodes;
    pthread_mutex_unlock(&g_matrix_mutex);
    return n;
}

void MATRIX_get_snapshot(matrix_snapshot_t *snap) {
    pthread_mutex_lock(&g_matrix_mutex);
    snap->numberOfActiveNodes = g_myMatrix.numberOfActiveNodes;
    memcpy(snap->idOfActiveNodes, g_myMatrix.idOfActiveNodes, sizeof(snap->idOfActiveNodes));
    memcpy(snap->link_quality,    g_myMatrix.link_quality,    sizeof(snap->link_quality));
    for(int i = 0; i < MAX_NODES; i++) {
        memcpy(snap->mst[i], g_spanningTree[i], MAX_NODES);
        snap->mst_ptrs[i] = snap->mst[i];
    }
    pthread_mutex_unlock(&g_matrix_mutex);
}

void MATRIX_print(void) {
    pthread_mutex_lock(&g_matrix_mutex);
    printf("[MATRIX] Nodes: ");
    for(int i = 0; i < g_myMatrix.numberOfActiveNodes; i++)
        printf("%d ", g_myMatrix.idOfActiveNodes[i]);
    printf("\n");
    for(int i = 0; i < g_myMatrix.numberOfActiveNodes; i++) {
        printf("N%d | ", g_myMatrix.idOfActiveNodes[i]);
        for(int x = 0; x < g_myMatrix.numberOfActiveNodes; x++) {
            if(i == x) printf("- ");
            else printf("%d ", g_myMatrix.matrix[i][x]);
        }
        printf(" (age: %.2f)\n", getEpoch() - g_myMatrix.creationTime[i]);
    }
    printf("\n");
    pthread_mutex_unlock(&g_matrix_mutex);
}

void MATRIX_updateLinkQuality(uint8_t node_id, bool timeout) {
    pthread_mutex_lock(&g_matrix_mutex);
    int8_t my_idx  = searchId(&g_myMatrix, getMyIP());
    int8_t node_idx = searchId(&g_myMatrix, node_id);
    if(my_idx == -1 || node_idx == -1) {
        pthread_mutex_unlock(&g_matrix_mutex);
        return;
    }
    if(timeout) {
        /* Degradação agressiva: -40 por slot miss (relay em ~2-3 misses) */
        if(g_myMatrix.link_quality[my_idx][node_idx] > 40)
            g_myMatrix.link_quality[my_idx][node_idx] -= 40;
        else
            g_myMatrix.link_quality[my_idx][node_idx] = 0;
    } else {
        /* Recuperação lenta: +3 por pacote recebido */
        if(g_myMatrix.link_quality[my_idx][node_idx] < 97)
            g_myMatrix.link_quality[my_idx][node_idx] += 3;
        else
            g_myMatrix.link_quality[my_idx][node_idx] = 100;
    }
    pthread_mutex_unlock(&g_matrix_mutex);
}

void primAlgorithm_weighted(void) {
    pthread_mutex_lock(&g_matrix_mutex);
    int num = g_myMatrix.numberOfActiveNodes;
    if(num <= 1) {
        for(int i = 0; i < MAX_NODES; i++) memset(g_spanningTree[i], 0, MAX_NODES);
        pthread_mutex_unlock(&g_matrix_mutex);
        return;
    }
    bool in_mst[MAX_NODES] = {false};
    int  parent[MAX_NODES];
    int  key[MAX_NODES];
    for(int i = 0; i < num; i++) { key[i] = 999; parent[i] = -1; }
    key[0] = 0;
    for(int count = 0; count < num; count++) {
        int min_key = 999, u = -1;
        for(int v = 0; v < num; v++)
            if(!in_mst[v] && key[v] < min_key) { min_key = key[v]; u = v; }
        if(u == -1) break;
        in_mst[u] = true;
        for(int v = 0; v < num; v++) {
            /* BUG 3 FIX (corrigido): AND original falhava quando o vizinho
             * ainda não tinha actualizado matrix[vizinho][eu] (staleness de
             * até 1 frame). OR inclui a aresta se pelo menos uma direcção
             * está confirmada. Arestas unidireccionais recebem penalidade
             * de 20 pontos para serem preteridas face a arestas confirmadas
             * nos dois sentidos quando a MST tem alternativas. */
            bool fwd = g_myMatrix.matrix[u][v];
            bool rev = g_myMatrix.matrix[v][u];
            if((fwd || rev) && !in_mst[v]) {
                uint8_t quality = g_myMatrix.link_quality[u][v];
                if(quality == 0) quality = g_myMatrix.link_quality[v][u];
                if(quality == 0) quality = INITIAL_LINK_QUALITY;
                if(!(fwd && rev) && quality > 20) quality -= 20; /* penalidade unidireccional */
                int cost = 100 - quality;
                if(cost < key[v]) { parent[v] = u; key[v] = cost; }
            }
        }
    }
    for(int i = 0; i < MAX_NODES; i++) memset(g_spanningTree[i], 0, MAX_NODES);
    for(int i = 1; i < num; i++)
        if(parent[i] != -1) {
            g_spanningTree[parent[i]][i] = 1;
            g_spanningTree[i][parent[i]] = 1;
        }
    pthread_mutex_unlock(&g_matrix_mutex);
}

uint8_t** MATRIX_getSpanningTree(void) {
    /* Devolve ponteiro directo — usar MATRIX_get_snapshot() para acesso seguro */
    return g_spanningTree;
}

void MATRIX_setLinkQuality(uint8_t node_id, uint8_t quality) {
    pthread_mutex_lock(&g_matrix_mutex);
    int8_t my_idx   = searchId(&g_myMatrix, getMyIP());
    int8_t node_idx = searchId(&g_myMatrix, node_id);
    if (my_idx != -1 && node_idx != -1)
        g_myMatrix.link_quality[my_idx][node_idx] = quality;
    pthread_mutex_unlock(&g_matrix_mutex);
}