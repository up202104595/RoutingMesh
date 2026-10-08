#!/bin/bash
# run-node.sh — limpa restos da execucao anterior e arranca o meshnode do
# metodo escolhido. Corre em CADA no (os 3 nos tem de usar o mesmo metodo).
#
# Uso:  sudo ./run-node.sh <l3|arp> <node_id> [num_nodes=3]
#   l3  -> ./meshnode_ipforward   (metodo Miguel)
#   arp -> ./meshnode_arp         (metodo Ana Morais)
# Env:  MESH_IFACE  interface ad-hoc (default: wlp5s0 se existir, senao wlan0)
#
# Requer os binarios: make both MESH_NET_PREFIX=172.20.10 MESH_PHY_IFACE=<iface>
# Nao mexe no modo ad-hoc nem no NetworkManager (tratam-se antes, como no guia).

usage() { echo "Uso: sudo $0 <l3|arp> <node_id> [num_nodes=3]"; exit 1; }

METHOD=${1:-}
NODE_ID=${2:-}
NUM_NODES=${3:-3}

case "$METHOD" in
    l3)  BIN=meshnode_ipforward ;;
    arp) BIN=meshnode_arp ;;
    *)   usage ;;
esac
[ -n "$NODE_ID" ] || usage
[ "$EUID" -eq 0 ] || { echo "ERRO: corre com sudo"; exit 1; }

DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -n "${MESH_IFACE:-}" ]; then
    IFACE=$MESH_IFACE
elif [ -d /sys/class/net/wlp5s0 ]; then
    IFACE=wlp5s0
else
    IFACE=wlan0
fi

if [ ! -x "$DIR/$BIN" ]; then
    echo "ERRO: $DIR/$BIN nao existe."
    echo "      Compila: make both MESH_NET_PREFIX=172.20.10 MESH_PHY_IFACE=$IFACE"
    exit 1
fi

# ── 1. Parar meshnodes anteriores ────────────────────────────────
# SIGINT primeiro: o meshnode limpa TUN/rotas/regras ao sair (SIGTERM nao limpa).
systemctl stop meshnode meshnode-metrics 2>/dev/null
pkill -INT -f 'meshnode_(ipforward|arp)' 2>/dev/null
pkill -INT -x meshnode 2>/dev/null
for _ in 1 2 3 4 5 6; do
    if ! pgrep -f 'meshnode_(ipforward|arp)' >/dev/null && ! pgrep -x meshnode >/dev/null; then
        break
    fi
    sleep 0.5
done
pkill -KILL -f 'meshnode_(ipforward|arp)' 2>/dev/null
pkill -KILL -x meshnode 2>/dev/null

# ── 2. Limpar restos (idempotente) ───────────────────────────────
iptables -t mangle -F 2>/dev/null
for _ in 1 2 3 4 5; do ip rule del fwmark 1 table 100 2>/dev/null; done
ip route flush table 100 2>/dev/null
for _ in 1 2 3; do ip rule del iif "tun$NODE_ID" lookup 200 2>/dev/null; done
ip route flush table 200 2>/dev/null
ip link delete "tun$NODE_ID" 2>/dev/null

# Entradas ARP injetadas pelo metodo ARP: o meshnode nunca as remove ao sair.
# Se ficarem, desviam o trafego do L3 (ex.: .3 continuaria a ir ao MAC do N2).
ip neigh show dev "$IFACE" nud permanent 2>/dev/null \
    | awk '$1 ~ /^172\.20\.10\./ {print $1}' \
    | while read -r addr; do ip neigh del "$addr" dev "$IFACE" 2>/dev/null; done

# ── 2b. ARP: MAC de cada no posto a mao no arranque (macs.conf) ───
# Cada IP fisico fica com o MAC do PROPRIO no, em entrada PERMANENT. Assim, antes
# de o roteamento mexer em nada, cada no fala direto com cada um dos outros.
if [ "$METHOD" = "arp" ]; then
    if [ -r "$DIR/macs.conf" ]; then
        while read -r id mac _; do
            case "$id" in ''|\#*) continue ;; esac
            [ "$id" = "$NODE_ID" ] && continue
            [ "$id" -le "$NUM_NODES" ] 2>/dev/null || continue
            if ip neigh replace "172.20.10.$id" lladdr "$mac" dev "$IFACE" nud permanent; then
                echo "[run-node] arp manual: 172.20.10.$id -> $mac"
            else
                echo "[run-node] AVISO: nao consegui pôr 172.20.10.$id -> $mac em $IFACE"
            fi
        done < "$DIR/macs.conf"
    else
        echo "[run-node] AVISO: falta $DIR/macs.conf — sem MACs manuais"
    fi
fi

# ── 3. Arrancar ──────────────────────────────────────────────────
echo "[run-node] metodo=$METHOD  binario=$BIN  no=$NODE_ID/$NUM_NODES  iface=$IFACE"
cd "$DIR" || exit 1
exec "./$BIN" "$NODE_ID" "$NUM_NODES"
