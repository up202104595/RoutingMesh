/*
 * net_ana.c — Setup de rede + rotas/ARP (MÉTODO ANA MORAIS)
 *
 * Data plane = kernel Linux (ip_forward + rota /32 dev wlan0 + ARP
 * estática). Ver net_ana.h para o desenho de 2 subredes.
 */

#include "net_ana.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <linux/if_tun.h>
#include <net/if.h>
#include <net/if_arp.h>
#include <arpa/inet.h>

/* canal ad-hoc — TEM de ser o mesmo em todos os nós (testbed usa 6).
 * sobrepor em compilação com -DMESH_CHANNEL=N */
#ifndef MESH_CHANNEL
#define MESH_CHANNEL 6
#endif

int net_ana_local_mac(const char *iface, uint8_t out[MAC_BYTES]) {
    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (fd < 0) return -1;
    struct ifreq ifr;
    memset(&ifr, 0, sizeof(ifr));
    strncpy(ifr.ifr_name, iface, IFNAMSIZ - 1);
    int rc = ioctl(fd, SIOCGIFHWADDR, &ifr);
    close(fd);
    if (rc < 0) return -1;
    memcpy(out, ifr.ifr_hwaddr.sa_data, MAC_BYTES);
    return 0;
}

/* cria a interface TUN e atribui-lhe o IP mesh (mesh_prefix.node_id/24) */
static int tun_create(const char *mesh_prefix, uint8_t node_id) {
    char cmd[256];
    snprintf(cmd, sizeof(cmd), "ip link delete tun%u 2>/dev/null", node_id);
    system(cmd);

    int fd = open("/dev/net/tun", O_RDWR);
    if (fd < 0) { perror("[NET-ANA] open /dev/net/tun"); return -1; }

    struct ifreq ifr;
    memset(&ifr, 0, sizeof(ifr));
    ifr.ifr_flags = IFF_TUN | IFF_NO_PI;
    snprintf(ifr.ifr_name, IFNAMSIZ, "tun%u", node_id);
    if (ioctl(fd, TUNSETIFF, &ifr) < 0) {
        perror("[NET-ANA] TUNSETIFF"); close(fd); return -1;
    }

    snprintf(cmd, sizeof(cmd),
        "ip addr add %s.%u/24 dev tun%u 2>/dev/null; "
        "ip link set tun%u up 2>/dev/null",
        mesh_prefix, node_id, node_id, node_id);
    system(cmd);
    printf("[NET-ANA] tun%u criada: IP mesh %s.%u/24\n",
           node_id, mesh_prefix, node_id);
    return fd;
}

int net_ana_setup(const char *phy_iface, const char *phy_prefix,
                  const char *mesh_prefix, uint8_t node_id) {
    char cmd[768];

    /* o NetworkManager reverte o modo ad-hoc — parar primeiro (como o
     * adhoc-start.sh do testbed Miguel) */
    system("systemctl stop NetworkManager 2>/dev/null");

    /* interface ad-hoc (igual ao testbed: essid/canal fixos, MESMO canal
     * em todos os nós senão não comunicam) */
    snprintf(cmd, sizeof(cmd),
        "ip link set %s down 2>/dev/null; "
        "iwconfig %s mode ad-hoc 2>/dev/null; "
        "iwconfig %s essid manet-mesh 2>/dev/null; "
        "iwconfig %s channel %d 2>/dev/null; "
        "ip link set %s up 2>/dev/null; "
        "ip addr flush dev %s 2>/dev/null; "
        "ip addr add %s.%u/28 dev %s 2>/dev/null",
        phy_iface, phy_iface, phy_iface, phy_iface, MESH_CHANNEL,
        phy_iface, phy_iface, phy_prefix, node_id, phy_iface);
    system(cmd);
    printf("[NET-ANA] Ad-hoc: essid=manet-mesh channel=%d IP=%s.%u/28 dev %s\n",
           MESH_CHANNEL, phy_prefix, node_id, phy_iface);

    /* ── sysctl (tese 3.2.2): o nó funciona como router ── */
    system("sysctl -wq net.ipv4.ip_forward=1 2>/dev/null"
           " || echo 1 > /proc/sys/net/ipv4/ip_forward");
    system("sysctl -wq net.ipv4.conf.all.accept_redirects=1 2>/dev/null");
    system("sysctl -wq net.ipv4.conf.default.accept_redirects=1 2>/dev/null");
    system("sysctl -wq net.ipv4.conf.all.send_redirects=0 2>/dev/null");
    system("sysctl -wq net.ipv4.conf.default.send_redirects=0 2>/dev/null");
    printf("[NET-ANA] ip_forward=1, accept_redirects=1, send_redirects=0\n");

    /* ── tun (IP mesh que as aplicações endereçam) ── */
    return tun_create(mesh_prefix, node_id);
}

void net_ana_teardown(const char *phy_iface, int tun_fd, uint8_t node_id) {
    if (tun_fd >= 0) close(tun_fd);
    char cmd[256];
    snprintf(cmd, sizeof(cmd),
        "ip neigh flush dev %s 2>/dev/null; "
        "ip link delete tun%u 2>/dev/null", phy_iface, node_id);
    system(cmd);
    printf("[NET-ANA] teardown: ARP flush em %s, tun%u removida\n",
           phy_iface, node_id);
}

/* ARP estática via ioctl (SIOCSARP): <ip_str> -> <mac_str> em iface */
static int arp_set(const char *iface, const char *ip_str, const char *mac_str) {
    int sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (sock < 0) { perror("[NET-ANA] socket"); return -1; }

    struct arpreq req;
    memset(&req, 0, sizeof(req));
    struct sockaddr_in *sin = (struct sockaddr_in *)&req.arp_pa;
    sin->sin_family = AF_INET;
    if (inet_pton(AF_INET, ip_str, &sin->sin_addr) != 1) { close(sock); return -1; }

    unsigned int mac[6];
    if (sscanf(mac_str, "%x:%x:%x:%x:%x:%x",
               &mac[0], &mac[1], &mac[2], &mac[3], &mac[4], &mac[5]) != 6) {
        close(sock); return -1;
    }
    for (int i = 0; i < 6; i++)
        req.arp_ha.sa_data[i] = (char)mac[i];

    req.arp_ha.sa_family = ARPHRD_ETHER;
    req.arp_flags = ATF_COM | ATF_PERM;      /* estática → força o relay */
    strncpy(req.arp_dev, iface, sizeof(req.arp_dev) - 1);

    int rc = ioctl(sock, SIOCSARP, &req);    /* batch via ioctl, não popen */
    close(sock);
    if (rc < 0) { perror("[NET-ANA] SIOCSARP"); return -1; }
    return 0;
}

static int arp_del(const char *iface, const char *ip_str) {
    int sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (sock < 0) return -1;
    struct arpreq req;
    memset(&req, 0, sizeof(req));
    struct sockaddr_in *sin = (struct sockaddr_in *)&req.arp_pa;
    sin->sin_family = AF_INET;
    inet_pton(AF_INET, ip_str, &sin->sin_addr);
    strncpy(req.arp_dev, iface, sizeof(req.arp_dev) - 1);
    ioctl(sock, SIOCDARP, &req);
    close(sock);
    return 0;
}

/* ── Mudança de rota = SÓ a tabela ARP, via ioctl (como a Ana) ──
 * O destino é um IP da subrede de wlan0 (on-link), por isso NENHUM
 * comando de linux / rota é necessário: a entrada ARP estática
 * sozinha força o frame a sair para o MAC do next-hop (tese 3.2.4). */
int net_ana_arp_set(const char *phy_iface, const char *ip, const char *mac_str) {
    return arp_set(phy_iface, ip, mac_str);   /* ioctl SIOCSARP, sem shell */
}

int net_ana_arp_del(const char *phy_iface, const char *ip) {
    return arp_del(phy_iface, ip);            /* ioctl SIOCDARP, sem shell */
}
