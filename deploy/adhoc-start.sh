#!/bin/bash
# adhoc-start.sh — Configura wlan0 em modo ad-hoc para RA-TDMAs+

source /etc/routingmesh/node.conf

echo "[ADHOC] A configurar wlan0 em modo ad-hoc (Node ${NODE_ID})..."

systemctl stop NetworkManager
ip link set wlan0 down
iwconfig wlan0 mode ad-hoc
iwconfig wlan0 essid manet-mesh
iwconfig wlan0 channel 6
ip link set wlan0 up
iptables -t mangle -F
for i in 1 2 3 4 5; do ip rule del fwmark 1 table 100 2>/dev/null; done
ip route flush table 100

echo "[ADHOC] wlan0 configurado: IP=172.20.10.${NODE_ID} ESSID=manet-mesh CH6"
iwconfig wlan0
