/*
 * wifi_quality.h  —  Leitura periódica de RSSI do chip WiFi
 *
 * Thread separada lê RSSI a cada 500ms via iw + arp.
 * O RX consulta a tabela em memória sem overhead.
 *
 * Miguel Almeida — FEUP 2025
 */

#ifndef WIFI_QUALITY_H
#define WIFI_QUALITY_H

#include <stdint.h>
#include "matrix.h"

#ifndef MESH_PHY_IFACE
#define MESH_PHY_IFACE "wlan0"
#endif

#ifndef MESH_NET_PREFIX
#define MESH_NET_PREFIX "172.20.10"
#endif

#define WIFI_QUALITY_INTERVAL_MS 500  /* lê RSSI a cada 500ms */

/* Inicia a thread de leitura periódica de RSSI */
void wifi_quality_start(void);

/* Para a thread */
void wifi_quality_stop(void);

/* Devolve qualidade 0-100 para o node_id (consulta tabela em memória) */
uint8_t wifi_quality_get(uint8_t node_id);

/* Mapeia RSSI dBm → qualidade 0-100 */
uint8_t wifi_rssi_to_quality(int rssi_dbm);

#endif /* WIFI_QUALITY_H */