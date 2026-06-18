/*
 * mac_table.c — Tabela MAC ↔ node ID (método Ana Morais, tese 3.2.3)
 */

#include "mac_table.h"
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <pthread.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <net/if.h>

#define MAX_MAC_ENTRIES 32

/* macArraySHM_t da tese: mutex + array + size */
static struct {
    pthread_mutex_t mut;
    macInfo_t       array[MAX_MAC_ENTRIES];
    size_t          size;
} g_mac;

static char g_str_buf[MAC_STR_LEN];

void mac_table_init(void) {
    pthread_mutex_init(&g_mac.mut, NULL);
    memset(g_mac.array, 0, sizeof(g_mac.array));
    g_mac.size = 0;
}

int mac_table_local_mac(const char *iface, uint8_t out[MAC_BYTES]) {
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

void mac_table_set(uint8_t node_id, const uint8_t mac_bytes[MAC_BYTES]) {
    if (node_id == 0) return;
    /* MAC todo a zeros = ainda não conhecido — ignora */
    int allzero = 1;
    for (int i = 0; i < MAC_BYTES; i++)
        if (mac_bytes[i]) { allzero = 0; break; }
    if (allzero) return;

    pthread_mutex_lock(&g_mac.mut);
    for (size_t i = 0; i < g_mac.size; i++) {
        if (g_mac.array[i].id == node_id) {
            memcpy(g_mac.array[i].mac_bytes, mac_bytes, MAC_BYTES);
            g_mac.array[i].valid = 1;
            pthread_mutex_unlock(&g_mac.mut);
            return;
        }
    }
    if (g_mac.size < MAX_MAC_ENTRIES) {
        macInfo_t *e = &g_mac.array[g_mac.size++];
        e->id = node_id;
        memcpy(e->mac_bytes, mac_bytes, MAC_BYTES);
        e->valid = 1;
    }
    pthread_mutex_unlock(&g_mac.mut);
}

void mac_table_del(uint8_t node_id) {
    pthread_mutex_lock(&g_mac.mut);
    for (size_t i = 0; i < g_mac.size; i++) {
        if (g_mac.array[i].id == node_id) {
            g_mac.array[i] = g_mac.array[g_mac.size - 1];
            g_mac.size--;
            break;
        }
    }
    pthread_mutex_unlock(&g_mac.mut);
}

int mac_table_get_bytes(uint8_t node_id, uint8_t out[MAC_BYTES]) {
    pthread_mutex_lock(&g_mac.mut);
    for (size_t i = 0; i < g_mac.size; i++) {
        if (g_mac.array[i].id == node_id && g_mac.array[i].valid) {
            memcpy(out, g_mac.array[i].mac_bytes, MAC_BYTES);
            pthread_mutex_unlock(&g_mac.mut);
            return 0;
        }
    }
    pthread_mutex_unlock(&g_mac.mut);
    return -1;
}

const char* mac_table_get_str(uint8_t node_id) {
    uint8_t m[MAC_BYTES];
    if (mac_table_get_bytes(node_id, m) != 0) return NULL;
    snprintf(g_str_buf, sizeof(g_str_buf),
             "%02x:%02x:%02x:%02x:%02x:%02x",
             m[0], m[1], m[2], m[3], m[4], m[5]);
    return g_str_buf;
}

void mac_table_print(void) {
    pthread_mutex_lock(&g_mac.mut);
    printf("\n+-------- MAC TABLE (Ana) --------+\n");
    for (size_t i = 0; i < g_mac.size; i++) {
        macInfo_t *e = &g_mac.array[i];
        printf("| Node %2u -> %02x:%02x:%02x:%02x:%02x:%02x |\n",
               e->id, e->mac_bytes[0], e->mac_bytes[1], e->mac_bytes[2],
               e->mac_bytes[3], e->mac_bytes[4], e->mac_bytes[5]);
    }
    if (g_mac.size == 0) printf("|         (vazia)                |\n");
    printf("+--------------------------------+\n\n");
    pthread_mutex_unlock(&g_mac.mut);
}
