/*
 * tun.c  —  Interface TUN virtual (Layer 3)
 *
 * Modo default (ip_forward): identico ao original.
 * Modo ARP (RELAY_METHOD_ARP): tun_write usa raw socket,
 * tun_arp_set manipula tabela ARP do kernel.
 *
 * Miguel Almeida — FEUP 2025
 */

#include "tun.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>

#include <sys/ioctl.h>
#include <sys/socket.h>
#include <linux/if_tun.h>
#include <net/if.h>
#include <net/if_arp.h>
#include <arpa/inet.h>
#include <netinet/ip.h>

#ifndef MESH_PHY_IFACE
#define MESH_PHY_IFACE "wlan0"
#endif

#ifndef MESH_NET_PREFIX
#define MESH_NET_PREFIX "172.20.10"
#endif

/* ── ARP helpers — só compilados no modo ARP ── */
#ifdef RELAY_METHOD_ARP
static int arp_set(const char *ip_str, const char *mac_str) {
    int sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (sock < 0) { perror("[TUN/ARP] socket"); return -1; }

    struct arpreq req;
    memset(&req, 0, sizeof(req));

    struct sockaddr_in *sin = (struct sockaddr_in *)&req.arp_pa;
    sin->sin_family = AF_INET;
    inet_pton(AF_INET, ip_str, &sin->sin_addr);

    unsigned int mac[6];
    sscanf(mac_str, "%x:%x:%x:%x:%x:%x",
           &mac[0], &mac[1], &mac[2], &mac[3], &mac[4], &mac[5]);
    for (int i = 0; i < 6; i++)
        req.arp_ha.sa_data[i] = (char)mac[i];

    req.arp_flags = ATF_COM | ATF_PERM;
    strncpy(req.arp_dev, MESH_PHY_IFACE, sizeof(req.arp_dev) - 1);

    if (ioctl(sock, SIOCSARP, &req) < 0) {
        perror("[TUN/ARP] SIOCSARP");
        close(sock);
        return -1;
    }
    close(sock);
    printf("[TUN/ARP] ARP: %s -> %s\n", ip_str, mac_str);
    return 0;
}

static int arp_del(const char *ip_str) {
    int sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (sock < 0) return -1;

    struct arpreq req;
    memset(&req, 0, sizeof(req));

    struct sockaddr_in *sin = (struct sockaddr_in *)&req.arp_pa;
    sin->sin_family = AF_INET;
    inet_pton(AF_INET, ip_str, &sin->sin_addr);
    strncpy(req.arp_dev, MESH_PHY_IFACE, sizeof(req.arp_dev) - 1);

    ioctl(sock, SIOCDARP, &req);
    close(sock);
    return 0;
}
#endif /* RELAY_METHOD_ARP */

int tun_open(uint8_t node_id) {

#ifdef RELAY_METHOD_ARP
    printf("[TUN] Metodo de relay: ARP trick (metodo Ana Morais)\n");
#else
    printf("[TUN] Metodo de relay: ip_forward + Netlink (metodo Miguel)\n");
#endif

    /* configura modo ad-hoc */
    char cmd[512];
    snprintf(cmd, sizeof(cmd),
        "ip link set " MESH_PHY_IFACE " down 2>/dev/null; "
        "iwconfig " MESH_PHY_IFACE " mode ad-hoc 2>/dev/null; "
        "iwconfig " MESH_PHY_IFACE " essid manet-mesh 2>/dev/null; "
        "iwconfig " MESH_PHY_IFACE " channel 6 2>/dev/null; "
        "ip link set " MESH_PHY_IFACE " up 2>/dev/null; "
        "ip addr flush dev " MESH_PHY_IFACE " 2>/dev/null; "
        "ip addr add %s.%u/28 dev " MESH_PHY_IFACE " 2>/dev/null",
        MESH_NET_PREFIX, node_id);
    system(cmd);
    printf("[TUN] Ad-hoc: essid=manet-mesh  channel=6  IP=%s.%u/28\n",
           MESH_NET_PREFIX, node_id);

    /* limpa interface anterior */
    snprintf(cmd, sizeof(cmd), "ip link delete tun%u 2>/dev/null", node_id);
    system(cmd);

    /* abre /dev/net/tun */
    int fd = open("/dev/net/tun", O_RDWR);
    if (fd < 0) { perror("[TUN] open /dev/net/tun"); return -1; }

    char iface_name[IFNAMSIZ];
    snprintf(iface_name, sizeof(iface_name), "tun%u", node_id);

    struct ifreq ifr;
    memset(&ifr, 0, sizeof(ifr));
    ifr.ifr_flags = IFF_TUN | IFF_NO_PI;
    strncpy(ifr.ifr_name, iface_name, IFNAMSIZ - 1);

    if (ioctl(fd, TUNSETIFF, &ifr) < 0) {
        perror("[TUN] ioctl TUNSETIFF"); close(fd); return -1;
    }

    printf("[TUN] Interface '%s' criada (fd=%d)\n", iface_name, fd);

    int sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (sock < 0) { perror("[TUN] socket auxiliar"); close(fd); return -1; }

    struct sockaddr_in *addr = (struct sockaddr_in *)&ifr.ifr_addr;
    addr->sin_family = AF_INET;
    char ip_str[32];
    snprintf(ip_str, sizeof(ip_str), "10.0.0.%u", node_id);
    inet_pton(AF_INET, ip_str, &addr->sin_addr);

    if (ioctl(sock, SIOCSIFADDR, &ifr) < 0) {
        perror("[TUN] ioctl SIOCSIFADDR"); close(sock); close(fd); return -1;
    }

    inet_pton(AF_INET, "255.255.255.0", &addr->sin_addr);
    if (ioctl(sock, SIOCSIFNETMASK, &ifr) < 0) {
        perror("[TUN] ioctl SIOCSIFNETMASK"); close(sock); close(fd); return -1;
    }

    if (ioctl(sock, SIOCGIFFLAGS, &ifr) < 0) {
        perror("[TUN] ioctl SIOCGIFFLAGS"); close(sock); close(fd); return -1;
    }
    ifr.ifr_flags |= IFF_UP | IFF_RUNNING;
    if (ioctl(sock, SIOCSIFFLAGS, &ifr) < 0) {
        perror("[TUN] ioctl SIOCSIFFLAGS"); close(sock); close(fd); return -1;
    }
    close(sock);

    /* --- A ALTERAÇÃO ESTÁ AQUI --- */
    /* rota 10.0.0.0/24 dev tunN forcando o IP de origem */
    snprintf(cmd, sizeof(cmd),
             "ip route add 10.0.0.0/24 dev tun%u src 10.0.0.%u 2>/dev/null", node_id, node_id);
    system(cmd);

#ifndef RELAY_METHOD_ARP
    /* ip_forward + rp_filter */
    system("echo 1 > /proc/sys/net/ipv4/ip_forward");
    system("echo 0 > /proc/sys/net/ipv4/conf/all/rp_filter");
    system("echo 0 > /proc/sys/net/ipv4/conf/default/rp_filter");
    printf("[TUN] ip_forward activado, rp_filter desactivado\n");

    /* ip rule: pacotes com src 10.0.0.0/24 mas NOT 10.0.0.{id}
     * (i.e. pacotes de relay injectados via tun_write) usam tabela 200
     * que tem rotas via wlan0 → kernel ip_forward directo para o destino */
    snprintf(cmd, sizeof(cmd),
        "ip rule del from 10.0.0.0/24 not from 10.0.0.%u/32 lookup 200 2>/dev/null; "
        "ip rule add from 10.0.0.0/24 not from 10.0.0.%u/32 lookup 200 priority 100",
        node_id, node_id);
    system(cmd);
    printf("[TUN] ip rule: relay src → tabela 200 (wlan0)\n");
#endif

    /* iptables */
    int tdma_port = 7000 + node_id;
    snprintf(cmd, sizeof(cmd),
        "iptables -t mangle -A OUTPUT -o " MESH_PHY_IFACE
        " -d 10.0.0.0/24 -j MARK --set-mark 1 2>/dev/null; "
        "iptables -t mangle -A OUTPUT -o " MESH_PHY_IFACE
        " -p udp --sport %d -j MARK --set-mark 0 2>/dev/null; "
        "ip rule add fwmark 1 table 100 2>/dev/null; "
        "ip route add default dev tun%u table 100 2>/dev/null",
        tdma_port, node_id);
    system(cmd);

    printf("[TUN] iptables: 10.0.0.0/24 -> tun%u (excluindo porta %d)\n",
           node_id, tdma_port);
    printf("[TUN] IP %s/24 atribuido, interface UP\n", ip_str);
    return fd;
}

void tun_close(int tun_fd, uint8_t node_id) {
    if (tun_fd >= 0) {
        close(tun_fd);
        char cmd[512];
        snprintf(cmd, sizeof(cmd),
                 "iptables -t mangle -F OUTPUT 2>/dev/null; "
                 "ip rule del fwmark 1 table 100 2>/dev/null; "
                 "ip route flush table 100 2>/dev/null; "
                 "ip rule del from 10.0.0.0/24 not from 10.0.0.%u/32 lookup 200 2>/dev/null; "
                 "ip route flush table 200 2>/dev/null; "
                 "ip route del 10.0.0.0/24 dev tun%u 2>/dev/null; "
                 "ip link delete tun%u 2>/dev/null", node_id, node_id, node_id);
        system(cmd);
        printf("[TUN] Interface tun%u removida\n", node_id);
    }
}

ssize_t tun_read(int tun_fd, uint8_t *buf, size_t buf_len) {
    ssize_t n = read(tun_fd, buf, buf_len);
    if (n < 0 && errno != EINTR && errno != EAGAIN)
        perror("[TUN] read");
    return n;
}

ssize_t tun_write(int tun_fd, const uint8_t *buf, size_t len) {
#ifdef RELAY_METHOD_ARP
    (void)tun_fd;
    if (len < sizeof(struct iphdr)) {
        fprintf(stderr, "[TUN] tun_write: pacote demasiado pequeno\n");
        return -1;
    }
    /* raw socket — kernel resolve MAC via tabela ARP manipulada */
    int sock = socket(AF_INET, SOCK_RAW, IPPROTO_RAW);
    if (sock < 0) { perror("[TUN/ARP] socket raw"); return -1; }

    int one = 1;
    setsockopt(sock, IPPROTO_IP, IP_HDRINCL, &one, sizeof(one));

    const struct iphdr *iph = (const struct iphdr *)buf;
    struct sockaddr_in dst = {0};
    dst.sin_family      = AF_INET;
    dst.sin_addr.s_addr = iph->daddr;

    ssize_t n = sendto(sock, buf, len, 0,
                       (struct sockaddr *)&dst, sizeof(dst));
    if (n < 0) perror("[TUN/ARP] sendto raw");
    close(sock);
    return n;

#else
    /* ip_forward — write simples na TUN */
    if (tun_fd < 0) {
        fprintf(stderr, "[TUN] tun_write: tun_fd invalido\n");
        return -1;
    }
    if (len < sizeof(struct iphdr)) {
        fprintf(stderr, "[TUN] tun_write: pacote demasiado pequeno (%zu bytes)\n", len);
        return -1;
    }
    ssize_t n = write(tun_fd, buf, len);
    if (n < 0) perror("[TUN] tun_write: write");
    return n;
#endif
}

uint8_t tun_get_dst_node(const uint8_t *ip_pkt, size_t len) {
    // 1. Verifica se o pacote TCP foi cortado
    if (len < sizeof(struct iphdr)) {
        printf("[TUN DEBUG] Pacote TCP rejeitado: tamanho (%zu) menor que IP header\n", len);
        return 0;
    }

    const struct iphdr *iph = (const struct iphdr *)ip_pkt;

    // 2. Verifica se o TCP está a gerar pacotes não-IPv4 (ex: IPv6)
    if (iph->version != 4) {
        printf("[TUN DEBUG] Pacote TCP rejeitado: nao e IPv4 (versao=%u)\n", iph->version);
        return 0;
    }

    uint32_t dst_full = ntohl(iph->daddr);
    uint8_t node = (uint8_t)(dst_full & 0xFF);

    // 3. Verifica se o TCP está a tentar enviar para fora da rede 10.0.0.X
    if ((dst_full >> 8) != 0x0A0000) { 
        struct in_addr dest_ip;
        dest_ip.s_addr = iph->daddr;
        printf("[TUN DEBUG] Pacote TCP ignorado: destino fora da subrede (%s)\n", inet_ntoa(dest_ip));
        // Dependendo da tua arquitetura, podes querer retornar 0 aqui
    }

    return node;
}

/* tun_arp_set / tun_arp_del — no-op no modo ip_forward */
int tun_arp_set(const char *virtual_ip, const char *next_hop_mac) {
#ifdef RELAY_METHOD_ARP
    return arp_set(virtual_ip, next_hop_mac);
#else
    (void)virtual_ip; (void)next_hop_mac;
    return 0;
#endif
}

int tun_arp_del(const char *virtual_ip) {
#ifdef RELAY_METHOD_ARP
    return arp_del(virtual_ip);
#else
    (void)virtual_ip;
    return 0;
#endif
}

const char* tun_get_relay_method(void) {
#ifdef RELAY_METHOD_ARP
    return "ARP trick (metodo Ana Morais)";
#else
    return "ip_forward + Netlink (metodo Miguel)";
#endif
}