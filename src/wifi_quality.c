/*
 * wifi_quality.c  —  Leitura periódica de RSSI do chip WiFi
 *
 * Thread separada lê RSSI a cada 500ms.
 * O RX consulta tabela em memória — sem overhead no caminho crítico.
 *
 * Miguel Almeida — FEUP 2025
 */

#include "wifi_quality.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <pthread.h>

/* ── tabela interna: node_id → qualidade 0-100 ── */
static uint8_t  g_quality[MAX_NODES + 1] = {0};
static pthread_mutex_t g_mutex = PTHREAD_MUTEX_INITIALIZER;
static volatile int    g_running = 0;
static pthread_t       g_thread;

/* ─────────────────────────────────────────────────────────────
 * wifi_rssi_to_quality()
 *
 * Threshold agressivo: abaixo de -70dBm a qualidade cai a zero,
 * forçando o MST a preferir o relay mesmo com o nó ainda "vivo".
 * ───────────────────────────────────────────────────────────── */
uint8_t wifi_rssi_to_quality(int rssi_dbm) {
    if (rssi_dbm >= -50) return 100;
    if (rssi_dbm <= -70) return 0;    /* corte agressivo: relay obrigatório */
    return (uint8_t)((rssi_dbm + 70) * 100 / 20);
}

/* ─────────────────────────────────────────────────────────────
 * parse_iw_station_dump()
 *
 * Lê "iw dev <iface> station dump" e preenche uma tabela
 * MAC → RSSI.
 * ───────────────────────────────────────────────────────────── */
typedef struct {
    char    mac[32];
    int     rssi;
} mac_rssi_t;

#define MAX_STATIONS 16

static int parse_iw_dump(mac_rssi_t *out, int max) {
    char cmd[128];
    snprintf(cmd, sizeof(cmd),
             "iw dev " MESH_PHY_IFACE " station dump 2>/dev/null");

    FILE *fp = popen(cmd, "r");
    if (!fp) return 0;

    char line[256];
    int  count    = 0;
    int  in_sta   = 0;
    char cur_mac[32] = {0};

    while (fgets(line, sizeof(line), fp) && count < max) {
        if (strncmp(line, "Station", 7) == 0) {
            in_sta = 0;
            if (sscanf(line, "Station %31s", cur_mac) == 1) {
                in_sta = 1;
                strncpy(out[count].mac, cur_mac, sizeof(out[count].mac) - 1);
                out[count].rssi = -100;
            }
            continue;
        }
        if (!in_sta) continue;

        int val;
        if (strstr(line, "signal:") && !strstr(line, "avg") &&
            sscanf(line, " signal: %d", &val) == 1) {
            out[count].rssi = val;
            count++;
            in_sta = 0;
        }
    }

    pclose(fp);
    return count;
}

/* ─────────────────────────────────────────────────────────────
 * get_ip_for_mac()
 *
 * Consulta "arp -n" para obter o IP de um MAC.
 * Devolve o último octeto (node_id) ou 0 se não encontrado.
 * ───────────────────────────────────────────────────────────── */
static uint8_t get_node_id_for_mac(const char *mac) {
    /* Tenta primeiro via ARP cache */
    FILE *fp = popen("arp -n 2>/dev/null", "r");
    if (fp) {
        char line[256];
        while (fgets(line, sizeof(line), fp)) {
            char lip[64], hwtype[16], lmac[32], flags[16], iface[32];
            if (sscanf(line, "%63s %15s %31s %15s %31s",
                       lip, hwtype, lmac, flags, iface) == 5) {
                if (strcasecmp(lmac, mac) == 0) {
                    int a, b, c, d;
                    if (sscanf(lip, "%d.%d.%d.%d", &a, &b, &c, &d) == 4) {
                        pclose(fp);
                        return (uint8_t)d;
                    }
                }
            }
        }
        pclose(fp);
    }

    /* Fallback: tenta via ip neigh (mais atualizado que arp em ad-hoc) */
    fp = popen("ip neigh 2>/dev/null", "r");
    if (!fp) return 0;

    char line[256];
    uint8_t node_id = 0;
    while (fgets(line, sizeof(line), fp)) {
        char lip[64], lmac[32], rest[128];
        if (sscanf(line, "%63s %127s", lip, rest) >= 1) {
            /* procura o MAC na linha */
            if (strcasestr(line, mac)) {
                int a, b, c, d;
                if (sscanf(lip, "%d.%d.%d.%d", &a, &b, &c, &d) == 4) {
                    node_id = (uint8_t)d;
                    break;
                }
            }
        }
    }
    pclose(fp);
    return node_id;
}

/* ─────────────────────────────────────────────────────────────
 * wifi_quality_loop() — thread periódica
 * ───────────────────────────────────────────────────────────── */
static void* wifi_quality_loop(void *arg) {
    (void)arg;

    printf("[WIFI] Thread de qualidade iniciada (intervalo=%dms)\n",
           WIFI_QUALITY_INTERVAL_MS);

    while (g_running) {
        mac_rssi_t stations[MAX_STATIONS];
        int n = parse_iw_dump(stations, MAX_STATIONS);

        for (int i = 0; i < n; i++) {
            uint8_t node_id = get_node_id_for_mac(stations[i].mac);
            if (node_id == 0 || node_id > MAX_NODES) continue;

            uint8_t quality = wifi_rssi_to_quality(stations[i].rssi);

            pthread_mutex_lock(&g_mutex);
            g_quality[node_id] = quality;
            pthread_mutex_unlock(&g_mutex);

            /* actualiza link_quality na matriz */
            MATRIX_setLinkQuality(node_id, quality);

            printf("[WIFI] Node %u  MAC=%s  RSSI=%d dBm  Quality=%u\n",
                   node_id, stations[i].mac, stations[i].rssi, quality);
        }

        usleep(WIFI_QUALITY_INTERVAL_MS * 1000);
    }

    printf("[WIFI] Thread de qualidade terminada\n");
    return NULL;
}

/* ─────────────────────────────────────────────────────────────
 * API pública
 * ───────────────────────────────────────────────────────────── */
void wifi_quality_start(void) {
    g_running = 1;
    pthread_create(&g_thread, NULL, wifi_quality_loop, NULL);
}

void wifi_quality_stop(void) {
    g_running = 0;
    pthread_join(g_thread, NULL);
}

uint8_t wifi_quality_get(uint8_t node_id) {
    if (node_id == 0 || node_id > MAX_NODES) return 0;
    pthread_mutex_lock(&g_mutex);
    uint8_t q = g_quality[node_id];
    pthread_mutex_unlock(&g_mutex);
    return q;
}