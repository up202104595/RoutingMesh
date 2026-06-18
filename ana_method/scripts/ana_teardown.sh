#!/bin/bash
# ana_teardown.sh — Reverte a configuração do método Ana Morais
# Uso: sudo ./ana_teardown.sh
iptables -t mangle -F OUTPUT 2>/dev/null || true
ip rule del fwmark 1 table 100 2>/dev/null || true
ip route flush table 100 2>/dev/null || true
echo "[ANA] Configuração revertida (iptables mangle + ip rule)."
