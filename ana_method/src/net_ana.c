/*
 * net_ana.c — Setup de rede + tabela ARP (MÉTODO ANA MORAIS)
 *
 * Data plane = kernel Linux (ip_forward + ARP estática). Ver net_ana.h.
 */

#include "net_ana.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <net/if.h>
#include <net/if_arp.h>
#include <arpa/inet.h>

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

int net_ana_setup(const char *iface, const char *prefix, uint8_t node_id) {
    char cmd[768];

    /* interface ad-hoc (igual ao testbed da tese: essid/canal fixos) */
    snprintf(cmd, sizeof(cmd),
        "ip link set %s down 2>/dev/null; "
        "iwconfig %s mode ad-hoc 2>/dev/null; "
        "iwconfig %s essid manet-mesh 2>/dev/null; "
        "iwconfig %s channel 1 2>/dev/null; "
        "ip link set %s up 2>/dev/null; "
        "ip addr flush dev %s 2>/dev/null; "
        "ip addr add %s.%u/28 dev %s 2>/dev/null",
        iface, iface, iface, iface, iface, iface, prefix, node_id, iface);
    system(cmd);
    printf("[NET-ANA] Ad-hoc: essid=manet-mesh channel=1 IP=%s.%u/28 dev %s\n",
           prefix, node_id, iface);

    /* ── sysctl (tese 3.2.2): o nó funciona como router ── */
    system("sysctl -wq net.ipv4.ip_forward=1 2>/dev/null"
           " || echo 1 > /proc/sys/net/ipv4/ip_forward");
    system("sysctl -wq net.ipv4.conf.all.accept_redirects=1 2>/dev/null");
    system("sysctl -wq net.ipv4.conf.default.accept_redirects=1 2>/dev/null");
    system("sysctl -wq net.ipv4.conf.all.send_redirects=0 2>/dev/null");
    system("sysctl -wq net.ipv4.conf.default.send_redirects=0 2>/dev/null");
    printf("[NET-ANA] ip_forward=1, accept_redirects=1, send_redirects=0\n");
    return 0;
}

void net_ana_teardown(const char *iface, uint8_t node_id) {
    (void)node_id;
    char cmd[256];
    snprintf(cmd, sizeof(cmd), "ip neigh flush dev %s 2>/dev/null", iface);
    system(cmd);
    printf("[NET-ANA] ARP flush em %s\n", iface);
}

int net_ana_arp_set(const char *iface, const char *ip_str, const char *mac_str) {
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

    /* entrada estática e permanente → sobrepõe-se à resolução dinâmica,
     * forçando o relay para o MAC do next-hop (tese 3.2.4) */
    req.arp_ha.sa_family = ARPHRD_ETHER;
    req.arp_flags = ATF_COM | ATF_PERM;
    strncpy(req.arp_dev, iface, sizeof(req.arp_dev) - 1);

    int rc = ioctl(sock, SIOCSARP, &req);   /* batch via ioctl, não popen/system */
    close(sock);
    if (rc < 0) { perror("[NET-ANA] SIOCSARP"); return -1; }
    return 0;
}

int net_ana_arp_del(const char *iface, const char *ip_str) {
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
