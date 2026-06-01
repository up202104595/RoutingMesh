#!/bin/bash
# install.sh — Instala serviços systemd nas Raspberrys
# Corre com: sudo bash install.sh <node_id>
#
# Nó 1 (AlphaBot):  sudo bash install.sh 1
# Nó 2 (Relay):     sudo bash install.sh 2
# Nó 3 (Base):      sudo bash install.sh 3

set -e

NODE_ID=${1:-""}
NUM_NODES=3

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

if [[ -z "$NODE_ID" ]]; then
    echo "Uso: sudo bash install.sh <node_id>"
    echo "  Ex: sudo bash install.sh 1"
    exit 1
fi

if [[ "$EUID" -ne 0 ]]; then
    echo "ERRO: corre com sudo"
    exit 1
fi

echo "=== RA-TDMAs+ Install — Nó $NODE_ID de $NUM_NODES ==="

# ── 1. Compila meshnode ───────────────────────────────────────────────────────
echo "[1/5] A compilar meshnode..."
cd "$PROJECT_DIR"
make clean
make MESH_NET_PREFIX="172.20.10" MESH_PHY_IFACE="wlan0"
cp meshnode /usr/local/bin/meshnode
cp metrics_collector.py /usr/local/bin/metrics_collector.py
echo "      OK: /usr/local/bin/meshnode"

# ── 2. Ficheiro de configuração do nó ────────────────────────────────────────
echo "[2/5] A criar /etc/routingmesh/node.conf..."
mkdir -p /etc/routingmesh
cat > /etc/routingmesh/node.conf <<EOF
NODE_ID=$NODE_ID
NUM_NODES=$NUM_NODES
EOF
echo "      OK: NODE_ID=$NODE_ID NUM_NODES=$NUM_NODES"

# ── 3. Serviço meshnode ───────────────────────────────────────────────────────
echo "[3/5] A instalar meshnode.service..."
cp "$SCRIPT_DIR/meshnode.service" /etc/systemd/system/meshnode.service
cp "$SCRIPT_DIR/meshnode-metrics.service" /etc/systemd/system/meshnode-metrics.service

# ── 4. Serviço específico do nó ───────────────────────────────────────────────
if [[ "$NODE_ID" -eq 1 ]]; then
    echo "[4/5] A instalar alphabot.service (Nó 1)..."
    # Ajusta o WorkingDirectory consoante o caminho real
    ALPHABOT_DIR="$PROJECT_DIR"
    sed "s|WorkingDirectory=.*|WorkingDirectory=$ALPHABOT_DIR|" \
        "$SCRIPT_DIR/alphabot.service" \
        > /etc/systemd/system/alphabot.service
    systemctl daemon-reload
    systemctl enable meshnode meshnode-metrics alphabot
    echo "      Serviços: meshnode, meshnode-metrics, alphabot"
elif [[ "$NODE_ID" -eq 2 ]]; then
    echo "[4/5] Nó 2 (relay puro) — só meshnode + metrics"
    systemctl daemon-reload
    systemctl enable meshnode meshnode-metrics
    echo "      Serviços: meshnode, meshnode-metrics"
elif [[ "$NODE_ID" -eq 3 ]]; then
    echo "[4/5] Nó 3 (base station) — só meshnode + metrics"
    echo "      (base_station.py corre manualmente)"
    systemctl daemon-reload
    systemctl enable meshnode meshnode-metrics
    echo "      Serviços: meshnode, meshnode-metrics"
fi

# ── 5. Diretório de logs ──────────────────────────────────────────────────────
echo "[5/5] A criar /var/log/routingmesh/..."
mkdir -p /var/log/routingmesh
chmod 755 /var/log/routingmesh

echo ""
echo "=== Instalação concluída ==="
echo ""
echo "Para iniciar agora:"
if [[ "$NODE_ID" -eq 1 ]]; then
    echo "  sudo systemctl start meshnode meshnode-metrics alphabot"
else
    echo "  sudo systemctl start meshnode meshnode-metrics"
fi
echo ""
echo "Para ver logs ao vivo:"
echo "  journalctl -u meshnode -f"
echo "  journalctl -u meshnode-metrics -f"
echo ""
echo "Para ver métricas:"
echo "  tail -f /var/log/routingmesh/metrics.jsonl"
echo "  python3 $(dirname $SCRIPT_DIR)/metrics_show.py"
