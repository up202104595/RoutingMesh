/*
 * ═══════════════════════════════════════════════════════════════
 * net_ana.h — Setup de rede + tabela ARP (MÉTODO ANA MORAIS)
 *
 * No método da Ana o DATA PLANE é o próprio kernel Linux:
 *   • ip_forward=1  → o nó reencaminha pacotes não destinados a si
 *   • tabela ARP estática (ioctl SIOCSARP) → IP destino resolve para
 *     o MAC do next-hop, fazendo o relay à Camada 2 sobre wlan0
 *   • os nós intermédios reencaminham IMEDIATAMENTE (não gated pelo
 *     slot TDMA) — exactamente como na tese (3.2 / 3.2.6 / 4.4)
 *
 * O framework apenas: partilha topologia, calcula a MST e mantém a
 * tabela ARP. NÃO transporta dados.
 * ═══════════════════════════════════════════════════════════════
 */

#ifndef NET_ANA_H
#define NET_ANA_H

#include <stdint.h>

#define MAC_BYTES 6

/* Configura a interface ad-hoc (wlan0), atribui o IP físico do nó,
 * activa ip_forward e os sysctl de redirects (tese 3.2.2). */
int  net_ana_setup(const char *iface, const char *prefix, uint8_t node_id);

/* Reverte regras adicionadas no arranque (best-effort). */
void net_ana_teardown(const char *iface, uint8_t node_id);

/* Lê o MAC físico da interface local para out[6]. 0 em sucesso. */
int  net_ana_local_mac(const char *iface, uint8_t out[MAC_BYTES]);

/* Instala/actualiza entrada ARP estática (ioctl SIOCSARP):
 *   ip_str (destino) -> mac_str (next-hop), na interface iface. */
int  net_ana_arp_set(const char *iface, const char *ip_str, const char *mac_str);

/* Remove entrada ARP (ioctl SIOCDARP). */
int  net_ana_arp_del(const char *iface, const char *ip_str);

#endif /* NET_ANA_H */
