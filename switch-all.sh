#!/bin/bash
# switch-all.sh — corre no N3 (PC). Troca o metodo de relay nos 3 nos:
# dispara o run-node.sh no N1 e no N2 por SSH e arranca o N3 localmente.
#
# Uso:  ./switch-all.sh <l3|arp>
#
# Pre-requisitos:
#   - a mesh esta a correr (o SSH vai pelos enderecos overlay 10.0.0.x, atraves
#     do relay). Se nao estiver, arranca cada no com run-node.sh.
#   - SSH para os Pi (ideal: chave, ssh-copy-id) e sudo sem password nos Pi.
#   - o repositorio esta na mesma pasta relativa a home em N1 e N2, e os
#     binarios estao compilados (make both ...).
#
# Ordem: N1 (o mais distante, ainda alcancavel pelo relay a correr), depois
# N2 (vizinho direto do N3), por fim N3 local. Logs de N1/N2 nos proprios Pi:
# /tmp/meshnode_<id>.log
#
# Env (opcional): REMOTE_USER (pi)  REMOTE_DIR (Documents/RoutingMesh)
#                 N1_HOST (10.0.0.1)  N2_HOST (10.0.0.2)

METHOD=${1:-}
case "$METHOD" in
    l3|arp) ;;
    *) echo "Uso: $0 <l3|arp>"; exit 1 ;;
esac

NUM_NODES=3
REMOTE_USER=${REMOTE_USER:-pi}
REMOTE_DIR=${REMOTE_DIR:-Documents/RoutingMesh}   # relativo a home remota
N1_HOST=${N1_HOST:-10.0.0.1}
N2_HOST=${N2_HOST:-10.0.0.2}
DIR="$(cd "$(dirname "$0")" && pwd)"

launch_remote() {   # $1 = node_id   $2 = host
    echo "[switch] N$1 ($2) -> $METHOD"
    # -n + redirects + setsid/nohup: o SSH regressa logo e o no continua a
    # correr mesmo que a ligacao caia quando a mesh reinicia.
    ssh -n -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new \
        "$REMOTE_USER@$2" \
        "cd $REMOTE_DIR && setsid nohup sudo ./run-node.sh $METHOD $1 $NUM_NODES </dev/null >/tmp/meshnode_$1.log 2>&1 &" \
        || { echo "[switch] ERRO: SSH para N$1 ($2) falhou — a abortar"; exit 1; }
}

launch_remote 1 "$N1_HOST"
sleep 2
launch_remote 2 "$N2_HOST"
sleep 2

echo "[switch] N3 (local) -> $METHOD"
exec sudo "$DIR/run-node.sh" "$METHOD" 3 "$NUM_NODES"
