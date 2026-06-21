#!/bin/bash
# ana_teardown.sh — limpa entradas ARP estáticas do método Ana Morais
# Uso: sudo ./ana_teardown.sh [iface]
IFACE="${1:-wlan0}"
ip neigh flush dev "$IFACE" 2>/dev/null || true
echo "[ANA] ARP flush em $IFACE."
