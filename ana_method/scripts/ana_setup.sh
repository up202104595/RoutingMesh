#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# ana_setup.sh — sysctl do método Ana Morais (tese 3.2.2)
#
# O binário meshnode_ana já aplica ad-hoc + ip_forward + ARP ao
# arrancar. Este script é opcional/documentação e garante o sysctl
# permanente, replicando fielmente a Secção 3.2.2 da dissertação.
#
# Uso:  sudo ./ana_setup.sh
# ═══════════════════════════════════════════════════════════════
set -e

echo "[ANA] sysctl (tese 3.2.2)..."
# net.ipv4.ip_forward = 1 — o nó reencaminha pacotes não destinados a si
sysctl -w net.ipv4.ip_forward=1
# aceitar ICMP redirects (a tese ativa-os para o routing funcionar)
sysctl -w net.ipv4.conf.all.accept_redirects=1
sysctl -w net.ipv4.conf.default.accept_redirects=1
# não enviar redirects (evita o nó responder com redirect em vez de relay)
sysctl -w net.ipv4.conf.all.send_redirects=0
sysctl -w net.ipv4.conf.default.send_redirects=0

echo "[ANA] sysctl aplicado. O reencaminhamento é feito pelo kernel via ARP."
