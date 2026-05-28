/*
 * ═══════════════════════════════════════════════════════════════
 * tx_queue.h  —  Fila thread-safe entre Thread TUN e Thread TX
 *
 * Produtor:  Thread TUN  (lê pacotes IP da interface tun0)
 * Consumidor: Thread TX  (drena durante o slot TDMA)
 * ═══════════════════════════════════════════════════════════════
 */

#ifndef TX_QUEUE_H
#define TX_QUEUE_H

#include <stdint.h>
#include <stddef.h>
#include <pthread.h>
#include <stdbool.h>

#define TX_QUEUE_MAX_PKT_SIZE  2048
#define TX_QUEUE_CAPACITY      64    /* máx pacotes em espera */

typedef struct tx_pkt {
    uint8_t  data[TX_QUEUE_MAX_PKT_SIZE];
    size_t   len;
    uint8_t  dst_id;    /* nó destino final (extraído do IP header) */
    struct tx_pkt *next;
} tx_pkt_t;

typedef struct tx_queue {
    tx_pkt_t       *head;
    tx_pkt_t       *tail;
    int             count;
    volatile bool   running;
    pthread_mutex_t lock;
} tx_queue_t;

/* Lifecycle */
tx_queue_t* tx_queue_create(void);
void        tx_queue_destroy(tx_queue_t *q);

/*
 * Push — chamado pelo Thread TUN.
 * Se a fila estiver cheia, descarta o pacote mais antigo (tail-drop).
 * Nunca bloqueia.
 */
void tx_queue_push(tx_queue_t *q, const uint8_t *data, size_t len, uint8_t dst_id);

/*
 * Pop — chamado pelo Thread TX durante o slot.
 * Retorna NULL se a fila estiver vazia (não bloqueia).
 */
tx_pkt_t* tx_queue_pop(tx_queue_t *q);

/* Número de pacotes em espera */
int tx_queue_size(tx_queue_t *q);

#endif /* TX_QUEUE_H */