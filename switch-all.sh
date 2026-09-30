#!/bin/bash
# switch-all.sh — corre no N3 (PC). Troca o metodo de relay nos 3 nos:
# dispara o run-node.sh no N1 e no N2 por SSH e arranca o N3 localmente.
#
# Uso:  ./switch-all.sh <l3|arp>
#
# Chamado tambem pela base_station.py (comando "arp"/"l3" ou botoes), com
# LOCAL_BG=1: o N3 arranca em background (log em /tmp/meshnode_3.log) e o SSH
# nunca pede password (BatchMode) — precisa de chave SSH.
#
# Pre-requisitos:
#   - a mesh esta a correr (o SSH vai pelos enderecos overlay 10.0.0.x, atraves
#     do relay). Se nao estiver, arranca cada no com run-node.sh.
#   - SSH por chave para os Pi (ssh-copy-id pi@10.0.0.1 ; ssh-copy-id pi@10.0.0.2)
#     e sudo sem password nos Pi e no PC (ou 'sudo -v' antes, no PC).
#   - o repositorio esta na mesma pasta relativa a home em N1 e N2, e os
#     binarios estao compilados (make both ...).
#
# Ordem: N1 (o mais distante, ainda alcancavel pelo relay a correr), depois
# N2 (vizinho direto do N3), por fim N3 local. Logs de N1/N2 nos proprios Pi:
# /tmp/meshnode_<id>.log
#
# Enderecos SSH de cada no: tenta primeiro o overlay 10.0.0.x (vai pela mesh a
# correr) e, se falhar, o fisico 172.20.10.x (1.o arranque, com os nos ao
# alcance uns dos outros). Assim o primeiro arranque tambem sai do PC.
#
# Env (opcional): REMOTE_USER (pi)  REMOTE_DIR (Documents/RoutingMesh)
#                 N1_HOST / N2_HOST (um unico endereco; desliga o fallback)
#                 LOCAL_BG=1  DRY_RUN=1 (so mostra o que faria)

METHOD=${1:-}
case "$METHOD" in
    l3|arp) ;;
    *) echo "Uso: $0 <l3|arp>"; exit 1 ;;
esac

NUM_NODES=3
REMOTE_USER=${REMOTE_USER:-pi}
REMOTE_DIR=${REMOTE_DIR:-Documents/RoutingMesh}   # relativo a home remota
N1_HOSTS=${N1_HOST:-10.0.0.1 172.20.10.1}
N2_HOSTS=${N2_HOST:-10.0.0.2 172.20.10.2}
LOCAL_BG=${LOCAL_BG:-0}
DRY_RUN=${DRY_RUN:-0}
DIR="$(cd "$(dirname "$0")" && pwd)"

SSH_OPTS=(-n -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new)
# sem terminal (chamado pela base_station.py): falhar logo em vez de pedir password
[ "$LOCAL_BG" = "1" ] && SSH_OPTS+=(-o BatchMode=yes)

run() {
    if [ "$DRY_RUN" = "1" ]; then echo "[dry-run] $*"; else "$@"; fi
}
pause() { [ "$DRY_RUN" = "1" ] || sleep "$1"; }

launch_remote() {   # $1 = node_id   $2 = lista de enderecos a tentar, por ordem
    local id=$1 h
    for h in $2; do
        echo "N$id ($h) -> $METHOD"
        # -n + redirects + setsid/nohup: o SSH regressa logo e o no continua a
        # correr mesmo que a ligacao caia quando a mesh reinicia.
        if run ssh "${SSH_OPTS[@]}" "$REMOTE_USER@$h" \
            "cd $REMOTE_DIR && setsid nohup sudo -n ./run-node.sh $METHOD $id $NUM_NODES </dev/null >/tmp/meshnode_$id.log 2>&1 &"; then
            return 0
        fi
        echo "  (SSH para $h falhou)"
    done
    echo "ERRO: SSH para N$id falhou em todos os enderecos ($2) — a abortar"
    exit 1
}

launch_remote 1 "$N1_HOSTS"
pause 2
launch_remote 2 "$N2_HOSTS"
pause 2

if [ "$LOCAL_BG" = "1" ]; then
    echo "N3 (local, em background) -> $METHOD  (log: /tmp/meshnode_3.log)"
    if [ "$DRY_RUN" = "1" ]; then
        echo "[dry-run] nohup sudo -n $DIR/run-node.sh $METHOD 3 $NUM_NODES > /tmp/meshnode_3.log &"
        exit 0
    fi
    nohup sudo -n "$DIR/run-node.sh" "$METHOD" 3 "$NUM_NODES" \
        </dev/null >/tmp/meshnode_3.log 2>&1 &
    exit 0
fi

echo "N3 (local) -> $METHOD"
if [ "$DRY_RUN" = "1" ]; then
    echo "[dry-run] exec sudo $DIR/run-node.sh $METHOD 3 $NUM_NODES"
    exit 0
fi
exec sudo "$DIR/run-node.sh" "$METHOD" 3 "$NUM_NODES"
