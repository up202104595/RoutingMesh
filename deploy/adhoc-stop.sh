#!/bin/bash
# adhoc-stop.sh — Restaura wlan0 para modo managed ao parar o serviço

IFACE="wlan0"

echo "[ADHOC] A restaurar ${IFACE} para modo managed..."

ip link set ${IFACE} down
iwconfig ${IFACE} mode managed
ip addr flush dev ${IFACE}
ip link set ${IFACE} up

systemctl start NetworkManager 2>/dev/null || true

echo "[ADHOC] ${IFACE} restaurado."
