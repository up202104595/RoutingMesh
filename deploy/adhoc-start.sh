#!/bin/bash
# adhoc-start.sh — Configura wlan0 em modo ad-hoc para RA-TDMAs+
# Chamado pelo adhoc.service no boot, antes do meshnode arrancar.
# O meshnode configura o IP TUN (10.0.0.x) — este script só trata da wlan0.

set -e

IFACE="wlan0"
ESSID="manet-mesh"
CHANNEL=6

# Lê NODE_ID do ficheiro de config (definido pelo install.sh)
source /etc/routingmesh/node.conf

PHY_IP="172.20.10.${NODE_ID}"
PHY_MASK="255.255.255.0"

echo "[ADHOC] A configurar ${IFACE} em modo ad-hoc (Node ${NODE_ID})..."

# Diz ao NetworkManager para nunca gerir esta interface
NM_CONF=/etc/NetworkManager/conf.d/99-routingmesh-unmanaged.conf
if [ ! -f "$NM_CONF" ]; then
    mkdir -p /etc/NetworkManager/conf.d
    cat > "$NM_CONF" <<EOF
[keyfile]
unmanaged-devices=interface-name:${IFACE}
EOF
    echo "[ADHOC] NetworkManager: ${IFACE} marcada como unmanaged"
fi

# Para serviços que possam interferir com a wlan
systemctl stop wpa_supplicant   2>/dev/null || true
systemctl stop NetworkManager   2>/dev/null || true
# Mata qualquer processo wpa_supplicant a correr na interface
pkill -f "wpa_supplicant.*${IFACE}" 2>/dev/null || true
sleep 0.5

# Coloca a interface down para poder mudar o modo
ip link set ${IFACE} down

# Modo ad-hoc + ESSID + canal
iwconfig ${IFACE} mode ad-hoc
iwconfig ${IFACE} essid ${ESSID}
iwconfig ${IFACE} channel ${CHANNEL}

# IP físico da rede ad-hoc
ip addr flush dev ${IFACE}
ip addr add ${PHY_IP}/${PHY_MASK} dev ${IFACE}

ip link set ${IFACE} up

# Aguarda a interface estabilizar
sleep 1

# Limpa regras iptables/ip rule que possam ter ficado de sessões anteriores
iptables -t mangle -F            2>/dev/null || true
iptables -F                      2>/dev/null || true
for i in $(seq 1 5); do
    ip rule del fwmark 1 table 100 2>/dev/null || break
done
ip route flush table 100         2>/dev/null || true

echo "[ADHOC] ${IFACE} configurado: IP=${PHY_IP} ESSID=${ESSID} CH${CHANNEL}"
iwconfig ${IFACE}
