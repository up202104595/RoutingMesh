/*
 * tx_queue.c  —  Fila thread-safe entre Thread TUN e Thread TX
 */

#include "tx_queue.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

tx_queue_t* tx_queue_create(void) {
    tx_queue_t *q = calloc(1, sizeof(tx_queue_t));
    if (!q) return NULL;
    q->running = true;
    pthread_mutex_init(&q->lock, NULL);
    printf("[TX_QUEUE] Criada (capacidade=%d)\n", TX_QUEUE_CAPACITY);
    return q;
}

void tx_queue_destroy(tx_queue_t *q) {
    if (!q) return;
    pthread_mutex_lock(&q->lock);
    tx_pkt_t *p = q->head;
    while (p) { tx_pkt_t *n = p->next; free(p); p = n; }
    pthread_mutex_unlock(&q->lock);
    pthread_mutex_destroy(&q->lock);
    free(q);
}

void tx_queue_push(tx_queue_t *q, const uint8_t *data, size_t len, uint8_t dst_id) {
    if (!q || len == 0 || len > TX_QUEUE_MAX_PKT_SIZE) return;

    pthread_mutex_lock(&q->lock);

    /* tail-drop: descarta o mais antigo se cheio */
    if (q->count >= TX_QUEUE_CAPACITY) {
        tx_pkt_t *old = q->head;
        q->head = old->next;
        if (!q->head) q->tail = NULL;
        q->count--;
        free(old);
        fprintf(stderr, "[TX_QUEUE] AVISO: fila cheia, pacote descartado\n");
    }

    tx_pkt_t *pkt = malloc(sizeof(tx_pkt_t));
    if (!pkt) { pthread_mutex_unlock(&q->lock); return; }

    memcpy(pkt->data, data, len);
    pkt->len    = len;
    pkt->dst_id = dst_id;
    pkt->next   = NULL;

    if (q->tail) { q->tail->next = pkt; q->tail = pkt; }
    else         { q->head = q->tail = pkt; }
    q->count++;

    pthread_mutex_unlock(&q->lock);
}

tx_pkt_t* tx_queue_pop(tx_queue_t *q) {
    if (!q) return NULL;
    pthread_mutex_lock(&q->lock);

    tx_pkt_t *pkt = q->head;
    if (pkt) {
        q->head = pkt->next;
        if (!q->head) q->tail = NULL;
        q->count--;
        pkt->next = NULL;
    }

    pthread_mutex_unlock(&q->lock);
    return pkt;
}

int tx_queue_size(tx_queue_t *q) {
    if (!q) return 0;
    pthread_mutex_lock(&q->lock);
    int n = q->count;
    pthread_mutex_unlock(&q->lock);
    return n;
}