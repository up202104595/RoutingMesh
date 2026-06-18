#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# ana_setup.sh — Configuração do kernel para o método Ana Morais
#
# Replica as configurações da tese:
#   • Secção 3.2.2 — parâmetros sysctl para o nó funcionar como router
#   • Code Block 3.4 — iptables mangle + ip rule (wlan0 -> tun)
#
# Nota: o binário (tun_open) já aplica as regras iptables/ip rule
# automaticamente ao arrancar. Este script garante o sysctl, que é
# permanente, e serve de documentação fiel à tese.
#
# Uso:  sudo ./ana_setup.sh <node_id> [phy_iface]
# ═══════════════════════════════════════════════════════════════
set -e

NODE_ID="${1:?Uso: sudo ./ana_setup.sh <node_id> [phy_iface]}"
PHY_IFACE="${2:-wlan0}"
TDMA_PORT=$((7000 + NODE_ID))

echo "[ANA] sysctl (tese 3.2.2)..."
# net.ipv4.ip_forward = 1 — o nó reencaminha pacotes não destinados a si
sysctl -w net.ipv4.ip_forward=1
# aceitar ICMP redirects (a tese ativa-os para o routing funcionar)
sysctl -w net.ipv4.conf.all.accept_redirects=1
sysctl -w net.ipv4.conf.default.accept_redirects=1
# não enviar redirects (evita o nó responder com redirect em vez de relay)
sysctl -w net.ipv4.conf.all.send_redirects=0
sysctl -w net.ipv4.conf.default.send_redirects=0

echo "[ANA] iptables mangle + ip rule (tese Code Block 3.4)..."
# marca o tráfego de aplicação para tun, excepto os pacotes UDP do framework
iptables -t mangle -C OUTPUT -o "$PHY_IFACE" -d 10.0.0.0/24 -j MARK --set-mark 1 2>/dev/null \
  || iptables -t mangle -A OUTPUT -o "$PHY_IFACE" -d 10.0.0.0/24 -j MARK --set-mark 1
iptables -t mangle -C OUTPUT -o "$PHY_IFACE" -p udp --sport "$TDMA_PORT" -j MARK --set-mark 0 2>/dev/null \
  || iptables -t mangle -A OUTPUT -o "$PHY_IFACE" -p udp --sport "$TDMA_PORT" -j MARK --set-mark 0

ip rule add fwmark 1 table 100 2>/dev/null || true
ip route add default dev "tun${NODE_ID}" table 100 2>/dev/null || true

echo "[ANA] Configuração aplicada para node ${NODE_ID} (iface=${PHY_IFACE}, porta TDMA=${TDMA_PORT})."
