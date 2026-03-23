/*
 * tun.c  —  Interface TUN virtual (Layer 3)
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
#include <linux/if.h>
#include <linux/if_tun.h>
#include <arpa/inet.h>
#include <netinet/ip.h>   /* struct iphdr */

/* ─────────────────────────────────────────────────────────────
 * tun_open()
 *
 * 1. Abre /dev/net/tun
 * 2. Configura como TUN (não TAP), sem cabeçalho Ethernet
 * 3. Atribui IP 10.0.0.<node_id>/24
 * 4. Activa a interface (IFF_UP)
 * ───────────────────────────────────────────────────────────── */
int tun_open(uint8_t node_id) {

    /* 1. Abre o dispositivo TUN */
    int fd = open("/dev/net/tun", O_RDWR);
    if (fd < 0) {
        perror("[TUN] open /dev/net/tun");
        fprintf(stderr, "[TUN] Precisa de root e módulo tun carregado "
                "(modprobe tun)\n");
        return -1;
    }

    /* 2. Configura como TUN (IFF_TUN = IP, não Ethernet)
     *    IFF_NO_PI = sem cabeçalho extra de 4 bytes — lemos IP puro */
    /* nome único por nó: tun1, tun2, tun3 ... */
    char iface_name[IFNAMSIZ];
    snprintf(iface_name, sizeof(iface_name), "tun%u", node_id);

    struct ifreq ifr;
    memset(&ifr, 0, sizeof(ifr));
    ifr.ifr_flags = IFF_TUN | IFF_NO_PI;
    strncpy(ifr.ifr_name, iface_name, IFNAMSIZ - 1);

    if (ioctl(fd, TUNSETIFF, &ifr) < 0) {
        perror("[TUN] ioctl TUNSETIFF");
        close(fd);
        return -1;
    }

    printf("[TUN] Interface '%s' criada (fd=%d)\n", iface_name, fd);

    /* 3. Atribui IP 10.0.0.<node_id>/24 via socket INET auxiliar */
    int sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (sock < 0) { perror("[TUN] socket auxiliar"); close(fd); return -1; }

    /* 3a. Endereço IP */
    struct sockaddr_in *addr = (struct sockaddr_in *)&ifr.ifr_addr;
    addr->sin_family = AF_INET;
    char ip_str[32];
    snprintf(ip_str, sizeof(ip_str), "10.0.0.%u", node_id);
    inet_pton(AF_INET, ip_str, &addr->sin_addr);

    if (ioctl(sock, SIOCSIFADDR, &ifr) < 0) {
        perror("[TUN] ioctl SIOCSIFADDR");
        close(sock); close(fd); return -1;
    }

    /* 3b. Máscara de rede /24 */
    inet_pton(AF_INET, "255.255.255.0", &addr->sin_addr);
    if (ioctl(sock, SIOCSIFNETMASK, &ifr) < 0) {
        perror("[TUN] ioctl SIOCSIFNETMASK");
        close(sock); close(fd); return -1;
    }

    /* 4. Activa a interface */
    if (ioctl(sock, SIOCGIFFLAGS, &ifr) < 0) {
        perror("[TUN] ioctl SIOCGIFFLAGS"); close(sock); close(fd); return -1;
    }
    ifr.ifr_flags |= IFF_UP | IFF_RUNNING;
    if (ioctl(sock, SIOCSIFFLAGS, &ifr) < 0) {
        perror("[TUN] ioctl SIOCSIFFLAGS"); close(sock); close(fd); return -1;
    }

    close(sock);

    /* Instala rota 10.0.0.0/24 dev tun<N> explicitamente.
     * O ioctl SIOCSIFADDR não garante criação automática da rota
     * de rede em todas as versões de kernel. Sem esta rota o Netlink
     * recusa rotas de host via 10.0.0.X com "Network is unreachable". */
    char route_cmd[128];
    snprintf(route_cmd, sizeof(route_cmd),
             "ip route add 10.0.0.0/24 dev tun%u 2>/dev/null", node_id);
    system(route_cmd);

    printf("[TUN] IP %s/24 atribuido, interface UP\n", ip_str);
    return fd;
}

/* ─────────────────────────────────────────────────────────────
 * tun_close()
 * ───────────────────────────────────────────────────────────── */
void tun_close(int tun_fd, uint8_t node_id) {
    if (tun_fd >= 0) {
        /* Fechar o fd destrói a interface automaticamente se não houver
         * mais referências. A linha abaixo garante limpeza mesmo que
         * haja referências pendentes (ex: crash anterior). */
        close(tun_fd);

        char cmd[128];
        snprintf(cmd, sizeof(cmd),
                 "ip route del 10.0.0.0/24 dev tun%u 2>/dev/null; "
                 "ip link delete tun%u 2>/dev/null", node_id, node_id);
        system(cmd);

        printf("[TUN] Interface tun%u removida\n", node_id);
    }
}

/* ─────────────────────────────────────────────────────────────
 * tun_read()  —  lê pacote IP da TUN (bloqueia)
 * ───────────────────────────────────────────────────────────── */
ssize_t tun_read(int tun_fd, uint8_t *buf, size_t buf_len) {
    ssize_t n = read(tun_fd, buf, buf_len);
    if (n < 0 && errno != EINTR && errno != EAGAIN)
        perror("[TUN] read");
    return n;
}

/* ─────────────────────────────────────────────────────────────
 * tun_write()
 *
 * Reinjecta o pacote IP original na interface física (wlan0)
 * usando um raw socket (IPPROTO_RAW).
 *
 * O kernel processa o pacote normalmente:
 *   - se IP dst == eu  → entrega à aplicação local
 *   - se IP dst != eu  → ip_forward=1 + ip route → forward automático
 *
 * Não bindamos ao interface directamente — bindamos ao IP destino
 * para que o kernel faça fragmentação/reassembly correctamente.
 * ───────────────────────────────────────────────────────────── */
ssize_t tun_write(int tun_fd, const uint8_t *buf, size_t len) {
    (void)tun_fd;  /* não usado — raw socket não precisa do tun_fd */

    if (len < sizeof(struct iphdr)) {
        fprintf(stderr, "[TUN] tun_write: pacote demasiado pequeno (%zu bytes)\n", len);
        return -1;
    }

    /* abre raw socket */
    int sock = socket(AF_INET, SOCK_RAW, IPPROTO_RAW);
    if (sock < 0) {
        perror("[TUN] tun_write: socket IPPROTO_RAW");
        return -1;
    }

    /* IP_HDRINCL — o pacote já tem cabeçalho IP, não adicionar outro */
    int one = 1;
    if (setsockopt(sock, IPPROTO_IP, IP_HDRINCL, &one, sizeof(one)) < 0) {
        perror("[TUN] tun_write: setsockopt IP_HDRINCL");
        close(sock);
        return -1;
    }

    /* extrai IP destino do cabeçalho IP do pacote */
    const struct iphdr *iph = (const struct iphdr *)buf;
    struct sockaddr_in dst = {0};
    dst.sin_family = AF_INET;
    dst.sin_addr.s_addr = iph->daddr;

    /* envia — bind ao endereço destino para kernel processar correctamente */
    ssize_t n = sendto(sock, buf, len, 0,
                       (struct sockaddr *)&dst, sizeof(dst));
    if (n < 0)
        perror("[TUN] tun_write: sendto raw");

    close(sock);
    return n;
}

/* ─────────────────────────────────────────────────────────────
 * tun_get_dst_node()
 *
 * Lê o campo ip->daddr do cabeçalho IPv4 e devolve o último
 * octeto — que corresponde ao node_id na rede 10.0.0.0/24.
 *
 * Exemplo: dst = 10.0.0.3  →  retorna 3
 * ───────────────────────────────────────────────────────────── */
uint8_t tun_get_dst_node(const uint8_t *ip_pkt, size_t len) {
    if (len < sizeof(struct iphdr)) return 0;

    const struct iphdr *iph = (const struct iphdr *)ip_pkt;

    /* verifica que é IPv4 */
    if (iph->version != 4) return 0;

    /* último octeto do IP destino */
    uint32_t dst = ntohl(iph->daddr);
    return (uint8_t)(dst & 0xFF);
}