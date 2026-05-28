/*
 * ip_route_netlink.h
 *
 * Gestão de rotas no kernel Linux via Netlink socket.
 * Sem fork/exec — custo ~50µs por rota.
 *
 * Miguel Almeida — FEUP 2025
 */

#ifndef IP_ROUTE_NETLINK_H
#define IP_ROUTE_NETLINK_H

#include <stdint.h>

/*
 * Activa ip_forward no kernel.
 * Chamar UMA VEZ em node_init(), antes de lançar as threads.
 * Equivalente a: echo 1 > /proc/sys/net/ipv4/ip_forward
 */
int ip_forward_enable(void);

/*
 * Adiciona rota no kernel:
 *   ip route add <dest_ip>/32 via <gw_ip> dev <iface>
 *
 * NLM_F_REPLACE garante que actualiza se já existir.
 * Retorna 0 em sucesso, -1 em erro.
 */
int ip_route_add(const char *dest_ip, const char *gw_ip, const char *iface);

/*
 * Remove rota do kernel:
 *   ip route del <dest_ip>/32 dev <iface>
 *
 * Retorna 0 em sucesso, -1 em erro.
 */
int ip_route_del(const char *dest_ip, const char *iface);

/*
 * Remove todas as rotas /32 da rede mesh.
 * Chamar em routing_manager_destroy().
 *
 * net_base  — ex: "10.0.0"
 * num_nodes — número máximo de nós
 * iface     — ex: "wlan0"
 */
void ip_route_flush_mesh(const char *net_base, uint8_t num_nodes,
                         const char *iface);

#endif /* IP_ROUTE_NETLINK_H */