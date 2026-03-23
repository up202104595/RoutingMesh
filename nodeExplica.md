Explicação das funções em node.c
Aqui está o que cada função faz:

signal_handler(int sig)
Manipulador de sinal que define g_running = 0 para parar graciosamente o programa quando o utilizador pressiona Ctrl+C.

get_time_us(void)
Retorna o tempo atual em microsegundos usando gettimeofday(). Usada para calcular slots TDMA e timestamps.

receiver_loop(void arg)*
Thread que recebe pacotes UDP:

Fica à escuta na porta do nó
Quando recebe um pacote, verifica se é do tipo MATRIX
Chama MATRIX_parsePkt() para desserializar e fazer merge da matriz recebida
tx_loop(void arg)*
Thread TDMA para transmissão:

Calcula qual é o slot TDMA atual
Se for o slot do nó (slot == node_id - 1), faz broadcast da sua matriz para os vizinhos
Serializa a matriz, adiciona cabeçalho TDMA e envia via UDP para todos os outros nós
Nos outros slots, dorme para não gastar CPU
node_init(uint8_t node_id, uint8_t num_nodes)
Inicializa um nó:

Aloca memória e configura ID, número de nós e porta
Cria socket UDP com SO_REUSEADDR
Faz bind à porta local
Inicializa a matriz local
node_run(node_t node)*
Inicia o nó:

Regista signal_handler para Ctrl+C
Cria threads para recetor e transmissor
Aguarda ambas as threads até terminar
node_destroy(node_t node)*
Liberta recursos:

Fecha o socket
Liberta a memória do nó