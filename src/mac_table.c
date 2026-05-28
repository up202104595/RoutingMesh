/*
 * mac_table.c — Tabela de MACs fisicos por node_id
 *
 * Miguel Almeida — FEUP 2025
 */

#include "mac_table.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#ifndef MESH_NET_PREFIX
#define MESH_NET_PREFIX "172.20.10"
#endif

#ifndef MAX_NODES
#define MAX_NODES 16
#endif

static char g_mac_table[MAX_NODES + 1][MAC_STR_LEN];
static int  g_mac_known[MAX_NODES + 1];

void mac_table_init(void) {
    memset(g_mac_table, 0, sizeof(g_mac_table));
    memset(g_mac_known, 0, sizeof(g_mac_known));
}

/*
 * Tenta obter MAC via "arp -n 172.20.10.X"
 * Parse da saída:
 *   172.20.10.8  ether  d8:3a:dd:33:f3:be  C  wlan0
 */
void mac_table_update(uint8_t node_id) {
    if (node_id == 0 || node_id > MAX_NODES) return;
    if (g_mac_known[node_id]) return;  /* já conhecido */

    char cmd[128];
    snprintf(cmd, sizeof(cmd),
             "arp -n %s.%u 2>/dev/null | awk 'NR==2{print $3}'",
             MESH_NET_PREFIX, node_id);

    FILE *fp = popen(cmd, "r");
    if (!fp) return;

    char mac[MAC_STR_LEN] = {0};
    if (fgets(mac, sizeof(mac), fp)) {
        /* remove newline */
        size_t len = strlen(mac);
        if (len > 0 && mac[len-1] == '\n')
            mac[len-1] = '\0';

        /* valida formato MAC */
        if (strlen(mac) == 17 && mac[2] == ':') {
            strncpy(g_mac_table[node_id], mac, MAC_STR_LEN - 1);
            g_mac_known[node_id] = 1;
            printf("[MAC] Node %u → %s\n", node_id, mac);
        } else {
            /* MAC nao disponivel ainda — tenta com ping primeiro */
            pclose(fp);
            snprintf(cmd, sizeof(cmd),
                     "ping -c 1 -W 1 %s.%u > /dev/null 2>&1",
                     MESH_NET_PREFIX, node_id);
            system(cmd);

            /* tenta arp novamente */
            snprintf(cmd, sizeof(cmd),
                     "arp -n %s.%u 2>/dev/null | awk 'NR==2{print $3}'",
                     MESH_NET_PREFIX, node_id);
            fp = popen(cmd, "r");
            if (!fp) return;

            if (fgets(mac, sizeof(mac), fp)) {
                len = strlen(mac);
                if (len > 0 && mac[len-1] == '\n')
                    mac[len-1] = '\0';
                if (strlen(mac) == 17 && mac[2] == ':') {
                    strncpy(g_mac_table[node_id], mac, MAC_STR_LEN - 1);
                    g_mac_known[node_id] = 1;
                    printf("[MAC] Node %u → %s (via ping)\n", node_id, mac);
                }
            }
        }
    }
    pclose(fp);
}

const char* mac_table_get(uint8_t node_id) {
    if (node_id == 0 || node_id > MAX_NODES) return NULL;
    if (!g_mac_known[node_id]) return NULL;
    return g_mac_table[node_id];
}

void mac_table_print(void) {
    printf("[MAC] Tabela de MACs:\n");
    for (int i = 1; i <= MAX_NODES; i++) {
        if (g_mac_known[i])
            printf("[MAC]   Node %2d → %s\n", i, g_mac_table[i]);
    }
}