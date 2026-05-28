/*
 * ═══════════════════════════════════════════════════════════════
 * ip_route_netlink.c
 *
 * Escreve/remove rotas na tabela do kernel via Netlink socket.
 * Equivalente a "ip route add/del" mas sem fork/exec.
 *
 * Custo: ~50µs por rota  (vs ~3ms com system("ip route ..."))
 *
 * Miguel Almeida — FEUP 2025
 * ═══════════════════════════════════════════════════════════════
 */

#include "ip_route_netlink.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>

#include <sys/socket.h>
#include <linux/netlink.h>
#include <linux/rtnetlink.h>
#include <arpa/inet.h>
#include <net/if.h>           /* if_nametoindex() */

/* ─────────────────────────────────────────────────────────────
 * ESTRUTURA INTERNA DE UM PEDIDO NETLINK
 *
 * Um pedido Netlink é composto por:
 *   1. nlmsghdr  — cabeçalho Netlink (tipo, flags, tamanho)
 *   2. rtmsg     — cabeçalho de routing (família, prefixo, protocolo...)
 *   3. rtattr[]  — atributos variáveis (destino IP, gateway IP, interface)
 * ───────────────────────────────────────────────────────────── */
typedef struct {
    struct nlmsghdr  nlh;
    struct rtmsg     rtm;
    char             buf[256];   /* espaço para rtattr's */
} nl_route_req_t;


/* ─────────────────────────────────────────────────────────────
 * AUXILIAR: adiciona um rtattr ao pedido
 * ───────────────────────────────────────────────────────────── */
static void nl_add_attr(nl_route_req_t *req, int type,
                        const void *data, int data_len)
{
    /* calcula posição do próximo atributo após o que já existe */
    int offset = NLMSG_ALIGN(req->nlh.nlmsg_len);
    struct rtattr *rta = (struct rtattr *)((char *)req + offset);

    rta->rta_type = type;
    rta->rta_len  = RTA_LENGTH(data_len);
    memcpy(RTA_DATA(rta), data, data_len);

    /* actualiza o tamanho total da mensagem */
    req->nlh.nlmsg_len = offset + rta->rta_len;
}


/* ─────────────────────────────────────────────────────────────
 * AUXILIAR: abre socket Netlink e envia pedido
 * Retorna 0 em sucesso, -1 em erro.
 * ───────────────────────────────────────────────────────────── */
static int nl_send(nl_route_req_t *req)
{
    /* abre socket Netlink do tipo NETLINK_ROUTE */
    int fd = socket(AF_NETLINK, SOCK_RAW, NETLINK_ROUTE);
    if (fd < 0) {
        perror("[IP_ROUTE] socket(AF_NETLINK)");
        return -1;
    }

    struct sockaddr_nl sa = {
        .nl_family = AF_NETLINK,
    };

    struct iovec  iov  = { req, req->nlh.nlmsg_len };
    struct msghdr msg  = {
        .msg_name    = &sa,
        .msg_namelen = sizeof(sa),
        .msg_iov     = &iov,
        .msg_iovlen  = 1,
    };

    int ret = 0;

    if (sendmsg(fd, &msg, 0) < 0) {
        perror("[IP_ROUTE] sendmsg");
        ret = -1;
        goto done;
    }

    /* lê a resposta ACK/NACK do kernel */
    char   reply[512];
    int    n = recv(fd, reply, sizeof(reply), 0);
    if (n < 0) {
        perror("[IP_ROUTE] recv");
        ret = -1;
        goto done;
    }

    struct nlmsghdr *nlh = (struct nlmsghdr *)reply;
    if (nlh->nlmsg_type == NLMSG_ERROR) {
        struct nlmsgerr *err = (struct nlmsgerr *)NLMSG_DATA(nlh);
        if (err->error != 0) {
            /* EEXIST ao fazer add é inofensivo — rota já existe */
            if (err->error != -EEXIST) {
                fprintf(stderr, "[IP_ROUTE] kernel error: %s\n",
                        strerror(-err->error));
                ret = -1;
            }
        }
    }

done:
    close(fd);
    return ret;
}


/* ─────────────────────────────────────────────────────────────
 * ip_forward_enable()
 * ───────────────────────────────────────────────────────────── */
int ip_forward_enable(void)
{
    FILE *f = fopen("/proc/sys/net/ipv4/ip_forward", "w");
    if (!f) {
        perror("[IP_ROUTE] fopen /proc/sys/net/ipv4/ip_forward");
        return -1;
    }
    fprintf(f, "1\n");
    fclose(f);
    printf("[IP_ROUTE] ip_forward activado\n");
    return 0;
}


/* ─────────────────────────────────────────────────────────────
 * ip_route_add()
 *
 * Adiciona:  ip route add <dest_ip>/32 via <gw_ip> dev <iface>
 *
 * dest_ip, gw_ip — IPv4 em formato "10.0.0.X" (string)
 * iface          — nome da interface, ex "wlan0"
 *
 * Retorna 0 em sucesso, -1 em erro.
 * ───────────────────────────────────────────────────────────── */
int ip_route_add(const char *dest_ip, const char *gw_ip, const char *iface)
{
    nl_route_req_t req;
    memset(&req, 0, sizeof(req));

    /* ── cabeçalho Netlink ── */
    req.nlh.nlmsg_len   = NLMSG_LENGTH(sizeof(struct rtmsg));
    req.nlh.nlmsg_type  = RTM_NEWROUTE;
    req.nlh.nlmsg_flags = NLM_F_REQUEST | NLM_F_ACK
                        | NLM_F_CREATE  | NLM_F_REPLACE;
    req.nlh.nlmsg_seq   = 1;

    /* ── cabeçalho de routing ── */
    req.rtm.rtm_family   = AF_INET;
    req.rtm.rtm_dst_len  = 32;           /* /32 — host route */
    req.rtm.rtm_src_len  = 0;
    req.rtm.rtm_tos      = 0;
    req.rtm.rtm_table    = RT_TABLE_MAIN;
    req.rtm.rtm_protocol = RTPROT_STATIC;
    req.rtm.rtm_scope    = RT_SCOPE_UNIVERSE;
    req.rtm.rtm_type     = RTN_UNICAST;

    /* ── atributo RTA_DST: endereço de destino ── */
    struct in_addr dst_addr;
    if (inet_pton(AF_INET, dest_ip, &dst_addr) != 1) {
        fprintf(stderr, "[IP_ROUTE] IP destino inválido: %s\n", dest_ip);
        return -1;
    }
    nl_add_attr(&req, RTA_DST, &dst_addr, sizeof(dst_addr));

    /* ── atributo RTA_GATEWAY: endereço do next-hop ── */
    struct in_addr gw_addr;
    if (inet_pton(AF_INET, gw_ip, &gw_addr) != 1) {
        fprintf(stderr, "[IP_ROUTE] IP gateway inválido: %s\n", gw_ip);
        return -1;
    }
    nl_add_attr(&req, RTA_GATEWAY, &gw_addr, sizeof(gw_addr));

    /* ── atributo RTA_OIF: índice da interface de saída ── */
    int ifindex = (int)if_nametoindex(iface);
    if (ifindex == 0) {
        fprintf(stderr, "[IP_ROUTE] interface '%s' não encontrada\n", iface);
        return -1;
    }
    nl_add_attr(&req, RTA_OIF, &ifindex, sizeof(ifindex));

    return nl_send(&req);
}


/* ─────────────────────────────────────────────────────────────
 * ip_route_del()
 *
 * Remove:  ip route del <dest_ip>/32
 *
 * Retorna 0 em sucesso, -1 em erro.
 * ───────────────────────────────────────────────────────────── */
int ip_route_del(const char *dest_ip, const char *iface)
{
    nl_route_req_t req;
    memset(&req, 0, sizeof(req));

    req.nlh.nlmsg_len   = NLMSG_LENGTH(sizeof(struct rtmsg));
    req.nlh.nlmsg_type  = RTM_DELROUTE;
    req.nlh.nlmsg_flags = NLM_F_REQUEST | NLM_F_ACK;
    req.nlh.nlmsg_seq   = 1;

    req.rtm.rtm_family  = AF_INET;
    req.rtm.rtm_dst_len = 32;
    req.rtm.rtm_table   = RT_TABLE_MAIN;
    req.rtm.rtm_scope   = RT_SCOPE_UNIVERSE;
    req.rtm.rtm_type    = RTN_UNICAST;

    struct in_addr dst_addr;
    if (inet_pton(AF_INET, dest_ip, &dst_addr) != 1) {
        fprintf(stderr, "[IP_ROUTE] IP destino inválido: %s\n", dest_ip);
        return -1;
    }
    nl_add_attr(&req, RTA_DST, &dst_addr, sizeof(dst_addr));

    int ifindex = (int)if_nametoindex(iface);
    if (ifindex == 0) {
        fprintf(stderr, "[IP_ROUTE] interface '%s' não encontrada\n", iface);
        return -1;
    }
    nl_add_attr(&req, RTA_OIF, &ifindex, sizeof(ifindex));

    return nl_send(&req);
}


/* ─────────────────────────────────────────────────────────────
 * ip_route_flush_mesh()
 *
 * Remove todas as rotas /32 que tenhamos adicionado.
 * Chamado em routing_manager_destroy().
 * ───────────────────────────────────────────────────────────── */
void ip_route_flush_mesh(const char *net_base, uint8_t num_nodes,
                         const char *iface)
{
    char dest_ip[32];
    for (uint8_t i = 1; i <= num_nodes; i++) {
        snprintf(dest_ip, sizeof(dest_ip), "%s.%u", net_base, i);
        ip_route_del(dest_ip, iface);   /* ignora erros — rota pode não existir */
    }
    printf("[IP_ROUTE] Rotas mesh removidas do kernel\n");
}