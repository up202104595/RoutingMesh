/*
 * ═══════════════════════════════════════════════════════════════
 * tun.h  —  Interface TUN virtual (Layer 3)
 *
 * Cria uma interface tun0 no OS. Pacotes IP enviados para tun0
 * por qualquer aplicação são lidos pelo Thread TUN e injectados
 * na tx_queue para transmissão no slot TDMA.
 *
 * No destino, o Thread RX escreve o pacote IP em tun0,
 * tornando-o visível à aplicação local transparentemente.
 *
 * Fluxo completo:
 *   [Aplicação/câmara]
 *       ↓  escreve para tun0
 *   [Thread TUN]  read(tun_fd) → tx_queue_push()
 *       ↓  slot TDMA
 *   [Thread TX]   tx_queue_pop() → MSG_DATA → sendto(next_hop)
 *       ↓  rede mesh
 *   [Thread RX]   recvfrom() → MSG_DATA → write(tun_fd)
 *       ↓
 *   [Aplicação destino]  lê de tun0
 * ═══════════════════════════════════════════════════════════════
 */

#ifndef TUN_H
#define TUN_H

#include <stdint.h>
#include <stddef.h>
#include <sys/types.h>

#define TUN_IFACE_NAME  "tun0"
#define TUN_MTU         1500

/*
 * Abre/cria a interface TUN.
 * Atribui o IP 10.0.0.<node_id>/24 e activa a interface.
 * Retorna o file descriptor ou -1 em erro.
 *
 * Requer root (CAP_NET_ADMIN).
 */
int tun_open(uint8_t node_id);

/*
 * Fecha a interface TUN.
 */
void tun_close(int tun_fd, uint8_t node_id);

/*
 * Lê um pacote IP da interface TUN.
 * Bloqueia até haver um pacote.
 * Retorna o número de bytes lidos ou -1 em erro.
 */
ssize_t tun_read(int tun_fd, uint8_t *buf, size_t buf_len);

/*
 * Escreve um pacote IP na interface TUN
 * (entrega ao stack IP local / aplicação destino).
 * Retorna o número de bytes escritos ou -1 em erro.
 */
ssize_t tun_write(int tun_fd, const uint8_t *buf, size_t len);

/*
 * Extrai o IP destino de um pacote IPv4 raw.
 * Retorna o último octeto (node_id do destino na rede 10.0.0.0/24).
 * Retorna 0 se o pacote for inválido.
 */
uint8_t tun_get_dst_node(const uint8_t *ip_pkt, size_t len);

#endif /* TUN_H */