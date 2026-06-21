/*
 * ═══════════════════════════════════════════════════════════════
 * net_ana.h — Setup de rede + rotas/ARP (MÉTODO ANA MORAIS)
 *
 * Desenho de 2 subredes, como na dissertação (3.2.5):
 *   • wlan0 (ad-hoc, real L2)  → prefixo FÍSICO  (ex. 172.20.10.x)
 *       é aqui que vivem os MACs e onde o kernel faz o relay ARP
 *   • tunN  (virtual)          → prefixo MESH    (ex. 10.0.0.x)
 *       é o IP que as aplicações endereçam (peer-to-peer, IP intacto)
 *
 * DATA PLANE = kernel Linux:
 *   • ip_forward=1 → o nó reencaminha o que não é para si
 *   • por destino: rota  <mesh_ip>/32 dev wlan0  + ARP estática
 *     <mesh_ip> -> MAC do next-hop  → o kernel envia o frame L2 ao
 *     next-hop sobre wlan0 e relaya hop a hop, IMEDIATAMENTE (não
 *     gated pelo slot TDMA) — exactamente como na tese (3.2 / 3.2.6)
 *
 * O framework apenas partilha topologia, calcula a MST e mantém estas
 * entradas. NÃO transporta dados.
 * ═══════════════════════════════════════════════════════════════
 */

#ifndef NET_ANA_H
#define NET_ANA_H

#include <stdint.h>

#define MAC_BYTES 6

/* Configura wlan0 ad-hoc (IP físico), cria a tunN (IP mesh), activa
 * ip_forward e os sysctl de redirects (tese 3.2.2). Devolve o fd da
 * tun (>=0) ou -1 em erro. */
int  net_ana_setup(const char *phy_iface, const char *phy_prefix,
                   const char *mesh_prefix, uint8_t node_id);

/* Fecha a tun e limpa rotas/ARP/tun (best-effort). */
void net_ana_teardown(const char *phy_iface, int tun_fd, uint8_t node_id);

/* Lê o MAC físico da interface local para out[6]. 0 em sucesso. */
int  net_ana_local_mac(const char *iface, uint8_t out[MAC_BYTES]);

/* Mudança de rota para um destino = SÓ a tabela ARP, via ioctl
 * (SIOCSARP, estática ATF_PERM). O destino é um IP da subrede de
 * wlan0 (on-link), por isso NENHUM comando de linux/rota é preciso —
 * a entrada ARP sozinha força o relay para o MAC do next-hop. */
int  net_ana_arp_set(const char *phy_iface, const char *ip, const char *mac_str);

/* Remove a entrada ARP de um destino (ioctl SIOCDARP). */
int  net_ana_arp_del(const char *phy_iface, const char *ip);

#endif /* NET_ANA_H */
