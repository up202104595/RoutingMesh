#!/bin/bash
# install-adhoc.sh — instala o serviço que põe o Pi em ad-hoc com o IP certo no
# boot, e desliga os serviços antigos (meshnode, meshnode-metrics, alphabot).
#
# Corre-se em CADA Pi (por SSH, a partir do PC):
#     sudo bash deploy/install-adhoc.sh <node_id>      # 1 = AlphaBot, 2 = relay
# e depois reinicia-se o Pi. É idempotente (pode repetir-se).
#
# Nao arranca o adhoc.service agora (reconfigurar o wlan0 cortaria o SSH em
# curso): so o ativa para o proximo boot. O daemon (meshnode) e o robo
# continuam a ser arrancados a mao, como na demonstracao.
#
# Desfazer:  sudo systemctl disable adhoc
#            sudo rm /etc/NetworkManager/conf.d/90-manet-unmanaged.conf
#            sudo reboot

set -e

NODE_ID=${1:-}
if ! [[ "$NODE_ID" =~ ^[1-9]$ ]]; then
    echo "Uso: sudo bash $0 <node_id>     (1 = AlphaBot, 2 = relay)"
    exit 1
fi

# PREFIX so serve para testar sem tocar no sistema
PREFIX=${PREFIX:-}
if [ -z "$PREFIX" ] && [ "$EUID" -ne 0 ]; then
    echo "ERRO: corre com sudo"; exit 1
fi

SRC="$(cd "$(dirname "$0")" && pwd)"
for f in adhoc.service adhoc-start.sh adhoc-stop.sh; do
    [ -f "$SRC/$f" ] || { echo "ERRO: falta $SRC/$f"; exit 1; }
done

CONF_DIR="$PREFIX/etc/routingmesh"
BIN_DIR="$PREFIX/usr/local/bin"
UNIT_DIR="$PREFIX/etc/systemd/system"
NM_DIR="$PREFIX/etc/NetworkManager/conf.d"
sc() { systemctl "$@" 2>/dev/null || true; }

echo "=== adhoc: no $NODE_ID  (IP 172.20.10.$NODE_ID) ==="

mkdir -p "$CONF_DIR" "$BIN_DIR" "$UNIT_DIR"
printf 'NODE_ID=%s\nNUM_NODES=3\n' "$NODE_ID" > "$CONF_DIR/node.conf"
cp "$SRC/adhoc-start.sh" "$SRC/adhoc-stop.sh" "$BIN_DIR/"
chmod +x "$BIN_DIR/adhoc-start.sh" "$BIN_DIR/adhoc-stop.sh"
cp "$SRC/adhoc.service" "$UNIT_DIR/adhoc.service"
echo "[1/4] node.conf, scripts e adhoc.service instalados"

# O NetworkManager nao pode mexer no wlan0 (desfaria o ad-hoc no boot)
if [ -d "$PREFIX/etc/NetworkManager" ]; then
    mkdir -p "$NM_DIR"
    printf '[keyfile]\nunmanaged-devices=interface-name:wlan0\n' > "$NM_DIR/90-manet-unmanaged.conf"
    echo "[2/4] NetworkManager: wlan0 deixa de ser gerido por ele"
else
    echo "[2/4] sem NetworkManager (nada a fazer)"
fi

# Servicos antigos: parar e desativar. wpa_supplicant tambem, como o install.sh.
sc daemon-reload
sc disable --now meshnode meshnode-metrics alphabot
sc disable wpa_supplicant
echo "[3/4] meshnode, meshnode-metrics e alphabot desativados e parados"

# SSH e adhoc no boot (adhoc so no proximo boot, nao agora)
sc enable ssh
sc enable adhoc
echo "[4/4] ssh e adhoc ativos no boot"

echo
echo "Feito. Reinicia o Pi: sudo reboot"
echo "Depois do boot, do PC (ja em ad-hoc): ping -c 3 172.20.10.$NODE_ID"
