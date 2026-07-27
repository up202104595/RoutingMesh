/*
 * tun.h  —  Interface TUN virtual (Layer 3)
 *
 * Relay via ip_forward: write(tun_fd) + rotas Netlink
 */

#ifndef TUN_H
#define TUN_H

#include <stdint.h>
#include <stddef.h>
#include <sys/types.h>

#define TUN_MTU 1500

/* Lifecycle */
int     tun_open(uint8_t node_id);
void    tun_close(int tun_fd, uint8_t node_id);

/* IO */
ssize_t tun_read(int tun_fd, uint8_t *buf, size_t buf_len);
ssize_t tun_write(int tun_fd, const uint8_t *buf, size_t len);

/* Routing helper */
uint8_t tun_get_dst_node(const uint8_t *ip_pkt, size_t len);

/* Info */
const char* tun_get_relay_method(void);

#endif /* TUN_H */