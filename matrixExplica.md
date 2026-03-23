Explicação pormenorizada das funções em matrix.c
getEpoch(void)
Retorna o tempo atual em segundos como double usando gettimeofday(). Usada para rastrear a idade dos nós.

getMyIP(void)
Retorna o ID do nó atual (g_myMatrix.myId).

compare(const void a, const void b)**
Função de comparação para qsort(). Compara dois uint8_t e retorna a diferença para ordenação crescente.

*searchId(tdma_matrix_t matrix, uint8_t id)
Procura um ID na lista de nós ativos. Retorna o índice se encontrado, senão retorna -1.

*removeIdList(tdma_matrix_t matrix, uint8_t pos)
Remove um nó da lista de IDs ativos:

Usa memmove() para deslocar arrays para a esquerda (IDs, idades e tempos de criação)
Decrementa o número de nós ativos
*removeIdMatrix(tdma_matrix_t matrix, uint8_t pos)
Remove um nó da matriz de adjacência:

Remove a linha (desloca todas as linhas abaixo para cima)
Remove a coluna (desloca todas as colunas à direita para a esquerda)
removeDeadLinks(void)
Crucial para timeout funcionar:

Itera sobre todos os nós
Calcula a idade de cada nó: age = tempo_atual - creationTime
Se age >= MAX_AGE (5 segundos), o nó é considerado morto
Remove o nó da matriz e das listas
Evita remover a si mesmo (seu próprio nó nunca "morre")
parameterSize()
Calcula os tamanhos (em bytes) de cada seção do payload serializado:

idOfActiveNodesSize: tamanho da lista de IDs
matrixSize: tamanho da matriz
ageSize: tamanho do array de idades
parameterPos()
Calcula as posições (offsets) de cada seção dentro do payload serializado.

serializeMatrix(tdma_matrix_t copy_ignored)
Converte a matriz global em bytes para envio via rede:

Remove nós mortos
Atualiza idades antes de enviar
Aloca buffer e copia sequencialmente: [numberOfActiveNodes | IDs | Matriz | Idades]
Retorna ponteiro para o buffer (deve ser libertado depois)
*deserializeMatrix(void rx_tdmapkt_ptr)
Desconverte bytes recebidos de volta em estrutura tdma_matrix_t:

Salta o cabeçalho TDMA
Extrai número de nós, IDs, matriz e idades nas suas posições corretas
Retorna nova estrutura alocada (deve ser libertada)
copyLine()
Copia uma linha de uma matriz para outra, adaptando-se se os IDs estão em ordem diferente.

discoverIds()
Mescla as listas de IDs de duas matrizes (A e B):

Começa com os IDs de A
Adiciona os IDs novos de B
Ordena o resultado
Imprime quando novos nós são descobertos
*matrix_update(tdma_matrix_t newMat, uint8_t other_IP)
Função principal de atualização:

Cria estrutura final com todos os IDs conhecidos (discovers)
Copia a sua própria matriz local
Atualiza com a matriz recebida (se mais recente)
Descarta nós mortos (age >= MAX_AGE)
Marca ligação direta: matrix[myID][otherIP] = 1
Atualiza a matriz global g_myMatrix
MATRIX_parsePkt()
Wrapper que:

Desserializa o pacote recebido
Chama matrix_update() para integrar a nova informação
Liberta memória
MATRIX_init(uint8_t my_id)
Inicializa a matriz:

Define o nó como ativo (a si mesmo)
Registra o tempo de criação
Aloca memória para a árvore geradora
MATRIX_get(void)
Retorna referência à matriz global g_myMatrix.

MATRIX_print(void)
Imprime a matriz em formato legível com cada nó e suas conexões + idade.