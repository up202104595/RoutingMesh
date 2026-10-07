#!/bin/bash
# demo-tmux.sh — UMA sessao tmux, NO PC, que corre tudo da demo.
#
#   janela "demo":      5 paineis visiveis ao mesmo tempo
#                         N3 (o proprio PC) | N1 (SSH) | N2 (SSH)
#                         BASE STATION      | ROBO (SSH ao N1)
#   janela "controlo":  uma shell livre no PC (para os comandos do bloqueio, etc.)
#
# Os Pi nao precisam de tmux: os nos dos Pi correm em primeiro plano, por SSH,
# dentro dos paineis do PC.
#
# A base e o robo ARRANCAM SOZINHOS, ao mesmo tempo que os nos: passados
# START_DELAY segundos (5) arranca a base e, ROBOT_DELAY segundos depois, o robo.
# Nao espera por nada nem testa nada.
#
# Uso (no PC, como utilizador normal — NAO com sudo):
#     ./demo-tmux.sh <l3|arp>
#   l3  -> video em UDP        arp -> video em TCP
#
# Navegacao tmux (prefixo = Ctrl+b):  n / p = janela seguinte/anterior,
# setas = painel, z = ampliar painel, d = sair sem parar nada.
# Voltar:  tmux attach -t demo
# Mudar de metodo / parar tudo:  sair com Ctrl+b d  e depois  tmux kill-session -t demo
# (chamar este script outra vez, de fora da sessao, tambem a substitui).
#
# Env: N1_HOST (pi@172.20.10.1)  N2_HOST (pi@172.20.10.2)  REMOTE_DIR
#      (Documents/RoutingMesh)  NO_ATTACH=1 (cria e nao entra)
#      N1_LOCAL=1 (o N1 e o robo NAO ficam no tmux: correm a parte, no monitor
#                  do Pi; o tmux fica so com N3, N2 e a base)
#      MANUAL_VIDEO=1 (base e robo ficam escritos, sem arrancar)
#      START_DELAY (5 s ate arrancar a base)  ROBOT_DELAY (2 s de a base ao robo)

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

S=demo

# Dentro da propria sessao 'demo' nao se pode substitui-la (matava este script).
if [ -n "$TMUX" ] && [ "$(tmux display-message -p '#S' 2>/dev/null)" = "$S" ]; then
    echo "ERRO: estas dentro da sessao '$S'. Sai com Ctrl+b d e corre isto de fora"
    echo "      (ou: tmux kill-session -t $S, num terminal normal)."
    exit 1
fi

DIR="$(cd "$(dirname "$0")" && pwd)"
for f in run-node.sh base_station.py; do
    [ -e "$DIR/$f" ] || { echo "ERRO: falta $DIR/$f"; exit 1; }
done
[ -x "$DIR/run-node.sh" ] || { echo "ERRO: run-node.sh nao e executavel (chmod +x run-node.sh)"; exit 1; }

N1=${N1_HOST:-pi@172.20.10.1}
N2=${N2_HOST:-pi@172.20.10.2}
RD=${REMOTE_DIR:-Documents/RoutingMesh}
START_DELAY=${START_DELAY:-5}
ROBOT_DELAY=${ROBOT_DELAY:-2}

# Se o comando terminar (ou der erro) o painel fica aberto com o codigo de saida.
wrap() { printf '%s; rc=$?; echo; echo "--- terminou (codigo $rc). Enter para fechar ---"; read' "$1"; }

CMD_N3="sudo ./run-node.sh $METHOD 3 3"
CMD_N1="ssh -t $N1 'cd $RD && sudo ./run-node.sh $METHOD 1 3'"
CMD_N2="ssh -t $N2 'cd $RD && sudo ./run-node.sh $METHOD 2 3'"
CMD_BASE="python3 base_station.py $VIDEO"
CMD_ROBOT="ssh -t $N1 'cd $RD && sudo python3 alphabot_node.py $VIDEO'"

tmux kill-session -t "$S" 2>/dev/null

# split-window com tamanho em percentagem: 'tmux >= 3.1' usa -l N%, as antigas -p N.
split_pct() { local pct=$1; shift; tmux split-window -l "${pct}%" "$@" 2>/dev/null || tmux split-window -p "$pct" "$@"; }

# ── janela "demo": em cima N3 | N1 | N2, em baixo BASE | ROBO ────
# (layout explicito: o 'tiled' do tmux escolhia 2 colunas x 3 linhas)
P3=$(tmux new-session -d -s "$S" -n demo -c "$DIR" -P -F '#{pane_id}' "$(wrap "$CMD_N3")") || { echo "ERRO: nao consegui criar a sessao tmux"; exit 1; }
if [ "${N1_LOCAL:-0}" = "1" ]; then
    # So N3, N2 e BASE: o N1 e o robo correm a parte, no monitor do Pi.
    PB=$(split_pct 40 -v -t "$P3" -c "$DIR" -P -F '#{pane_id}' "$(wrap "sleep $START_DELAY; $CMD_BASE")")
    P2=$(split_pct 50 -h -t "$P3" -c "$DIR" -P -F '#{pane_id}' "$(wrap "$CMD_N2")")
    P1=""; PR=""
else
    if [ "${MANUAL_VIDEO:-0}" = "1" ]; then
        PB=$(split_pct 40 -v -t "$P3" -c "$DIR" -P -F '#{pane_id}')
        PR=$(split_pct 50 -h -t "$PB" -c "$DIR" -P -F '#{pane_id}')
        tmux send-keys -t "$PB" "$CMD_BASE"
        tmux send-keys -t "$PR" "$CMD_ROBOT"
    else
        PB=$(split_pct 40 -v -t "$P3" -c "$DIR" -P -F '#{pane_id}' "$(wrap "sleep $START_DELAY; $CMD_BASE")")
        PR=$(split_pct 50 -h -t "$PB" -c "$DIR" -P -F '#{pane_id}' "$(wrap "sleep $((START_DELAY + ROBOT_DELAY)); $CMD_ROBOT")")
    fi
    P1=$(split_pct 67 -h -t "$P3" -c "$DIR" -P -F '#{pane_id}' "$(wrap "$CMD_N1")")
    P2=$(split_pct 50 -h -t "$P1" -c "$DIR" -P -F '#{pane_id}' "$(wrap "$CMD_N2")")
fi
tmux select-pane -t "$P3" -T "N3 - PC ($METHOD)"
[ -n "$P1" ] && tmux select-pane -t "$P1" -T "N1 - AlphaBot ($METHOD)"
tmux select-pane -t "$P2" -T "N2 - relay ($METHOD)"
tmux select-pane -t "$PB" -T "BASE STATION ($VIDEO)"
[ -n "$PR" ] && tmux select-pane -t "$PR" -T "ROBO N1 ($VIDEO)"

# ── janela "controlo": shell livre no PC ─────────────────────────
tmux new-window -t "$S:" -n controlo -c "$DIR" >/dev/null

tmux set-option -t "$S" mouse on >/dev/null
tmux set-option -t "$S" pane-border-status top >/dev/null
tmux set-option -t "$S" pane-border-format " #{pane_title} " >/dev/null
tmux select-window -t "$S:demo"
tmux select-pane -t "$P3"

echo "[demo-tmux] sessao '$S' criada em ${METHOD^^} (video $VIDEO)."
if [ "${NO_ATTACH:-0}" = "1" ]; then
    echo "            entrar:  tmux attach -t $S"
elif [ -n "$TMUX" ]; then
    tmux switch-client -t "$S"
else
    exec tmux attach -t "$S"
fi
