#!/bin/bash
# demo-tmux.sh — UMA sessao tmux, NO PC, que corre tudo da demo:
#
#   janela "nos":    3 paineis — N3 (o proprio PC), N1 e N2 (por SSH aos Pi)
#   janela "video":  2 paineis — base_station.py e alphabot_node.py (por SSH ao N1)
#
# Os Pi nao precisam de tmux: os nos dos Pi correm em primeiro plano, por SSH,
# dentro dos paineis do PC.
#
# Uso (no PC, como utilizador normal — NAO com sudo):
#     ./demo-tmux.sh <l3|arp>
#   l3  -> video em UDP        arp -> video em TCP
#
# Na janela "video" os comandos da base e do robo ficam ESCRITOS mas nao
# executados: carrega Enter quando a janela "nos" mostrar o [GATE]. A base
# arranca antes do robo.
#
# Navegacao tmux (prefixo = Ctrl+b):  n / p = janela seguinte/anterior,
# setas = painel, z = ampliar painel, d = sair sem parar nada.
# Voltar:  tmux attach -t demo        Parar tudo:  tmux kill-session -t demo
# Chamar outra vez com o outro metodo substitui a sessao.
#
# Env: N1_HOST (pi@172.20.10.1)  N2_HOST (pi@172.20.10.2)  REMOTE_DIR
#      (Documents/RoutingMesh)  NO_ATTACH=1 (cria a sessao e nao entra nela)

usage() { echo "Uso: $0 <l3|arp>   (no PC, sem sudo)"; exit 1; }

METHOD=${1:-}
case "$METHOD" in
    l3)  VIDEO=udp ;;
    arp) VIDEO=tcp ;;
    *)   usage ;;
esac

if [ "$EUID" -eq 0 ] && [ "${DEMO_ALLOW_ROOT:-0}" != "1" ]; then
    echo "ERRO: nao corras com sudo. Os 'sudo' estao dentro dos paineis (pedem a password la)."
    exit 1
fi
command -v tmux >/dev/null || { echo "ERRO: o tmux nao esta instalado no PC (sudo apt install tmux)"; exit 1; }

DIR="$(cd "$(dirname "$0")" && pwd)"
for f in run-node.sh base_station.py; do
    [ -e "$DIR/$f" ] || { echo "ERRO: falta $DIR/$f"; exit 1; }
done
[ -x "$DIR/run-node.sh" ] || { echo "ERRO: run-node.sh nao e executavel (chmod +x run-node.sh)"; exit 1; }

S=demo
N1=${N1_HOST:-pi@172.20.10.1}
N2=${N2_HOST:-pi@172.20.10.2}
RD=${REMOTE_DIR:-Documents/RoutingMesh}

# Se o comando terminar (ou der erro) o painel fica aberto com o codigo de saida.
wrap() { printf '%s; rc=$?; echo; echo "--- terminou (codigo $rc). Enter para fechar ---"; read' "$1"; }

CMD_N3="sudo ./run-node.sh $METHOD 3 3"
CMD_N1="ssh -t $N1 'cd $RD && sudo ./run-node.sh $METHOD 1 3'"
CMD_N2="ssh -t $N2 'cd $RD && sudo ./run-node.sh $METHOD 2 3'"
CMD_BASE="python3 base_station.py $VIDEO"
CMD_ROBOT="ssh -t $N1 'cd $RD && sudo python3 alphabot_node.py $VIDEO'"

tmux kill-session -t "$S" 2>/dev/null

# ── janela "nos": N3 | N1 / N2 ───────────────────────────────────
P3=$(tmux new-session -d -s "$S" -n nos -c "$DIR" -P -F '#{pane_id}' "$(wrap "$CMD_N3")") || { echo "ERRO: nao consegui criar a sessao tmux"; exit 1; }
P1=$(tmux split-window -h -t "$P3" -c "$DIR" -P -F '#{pane_id}' "$(wrap "$CMD_N1")")
P2=$(tmux split-window -v -t "$P1" -c "$DIR" -P -F '#{pane_id}' "$(wrap "$CMD_N2")")
tmux select-pane -t "$P3" -T "N3 - PC ($METHOD)"
tmux select-pane -t "$P1" -T "N1 - AlphaBot ($METHOD)"
tmux select-pane -t "$P2" -T "N2 - relay ($METHOD)"

# ── janela "video": base | robo (comandos escritos, sem Enter) ───
PB=$(tmux new-window -t "$S" -n video -c "$DIR" -P -F '#{pane_id}')
PR=$(tmux split-window -h -t "$PB" -c "$DIR" -P -F '#{pane_id}')
tmux select-pane -t "$PB" -T "BASE STATION ($VIDEO)"
tmux select-pane -t "$PR" -T "ROBO N1 ($VIDEO)"
tmux send-keys -t "$PB" "$CMD_BASE"
tmux send-keys -t "$PR" "$CMD_ROBOT"

tmux set-option -t "$S" mouse on >/dev/null
tmux set-option -t "$S" pane-border-status top >/dev/null
tmux set-option -t "$S" pane-border-format " #{pane_title} " >/dev/null
tmux select-window -t "$S:nos"

echo "[demo-tmux] sessao '$S' criada em ${METHOD^^} (video $VIDEO)."
if [ "${NO_ATTACH:-0}" = "1" ]; then
    echo "            entrar:  tmux attach -t $S"
elif [ -n "$TMUX" ]; then
    tmux switch-client -t "$S"
else
    exec tmux attach -t "$S"
fi
