/*
 * tun.h  —  Interface TUN virtual (Layer 3)
 *
 * Suporta dois metodos de relay:
 *   - ip_forward (default): write(tun_fd) + Netlink routes
 *   - ARP trick (RELAY_METHOD=arp): raw socket + ARP manipulation
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

/* ARP trick (metodo Ana Morais) — no-op no modo ip_forward */
int tun_arp_set(const char *virtual_ip, const char *next_hop_mac);
int tun_arp_del(const char *virtual_ip);

/* Info */
const char* tun_get_relay_method(void);

#endif /* TUN_H */