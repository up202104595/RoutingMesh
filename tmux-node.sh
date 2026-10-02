#!/bin/bash
# tmux-node.sh — arranca o daemon do no numa sessao tmux "mesh", em segundo plano.
# A sessao sobrevive a quedas de SSH e a fechar o terminal.
#
# Uso (em CADA no, como root):
#     sudo ./tmux-node.sh <l3|arp> <node_id> [num_nodes=3]
#
# Ver o que o no esta a escrever:
#     sudo tmux attach -t mesh          (sair sem parar o no: Ctrl+b e depois d)
#     sudo tmux capture-pane -p -t mesh | tail -20      (so espreitar)
# Parar o no:
#     sudo tmux kill-session -t mesh
#
# Se ja existir uma sessao "mesh" (de outro metodo, por exemplo), e terminada e
# substituida; o run-node.sh limpa o que ela deixou. Se o no terminar ou der
# erro, a sessao fica aberta com a mensagem, para se ler com o attach/capture.

usage() { echo "Uso: sudo $0 <l3|arp> <node_id> [num_nodes=3]"; exit 1; }

METHOD=${1:-}
ID=${2:-}
N=${3:-3}
SESSION=mesh

case "$METHOD" in l3|arp) ;; *) usage ;; esac
[[ "$ID" =~ ^[0-9]+$ ]] || usage
[ "$EUID" -eq 0 ] || { echo "ERRO: corre com sudo (a sessao tmux pertence ao root, e o run-node.sh precisa dele)"; exit 1; }
command -v tmux >/dev/null || { echo "ERRO: o tmux nao esta instalado (sudo apt install tmux; precisa de internet)"; exit 1; }

DIR="$(cd "$(dirname "$0")" && pwd)"
[ -x "$DIR/run-node.sh" ] || { echo "ERRO: $DIR/run-node.sh nao existe ou nao e executavel (chmod +x run-node.sh)"; exit 1; }

tmux kill-session -t "$SESSION" 2>/dev/null

# A sessao fica aberta no fim (read), para as mensagens de erro nao se perderem.
tmux new-session -d -s "$SESSION" -c "$DIR" \
  "./run-node.sh $METHOD $ID $N; rc=\$?; echo; echo \"--- o no terminou (codigo \$rc). Enter para fechar ---\"; read" \
  || { echo "ERRO: nao consegui criar a sessao tmux"; exit 1; }

echo "[tmux-node] no $ID em $METHOD arrancado na sessao tmux '$SESSION'"
echo "            ver:    sudo tmux attach -t $SESSION      (sair: Ctrl+b, d)"
echo "            parar:  sudo tmux kill-session -t $SESSION"
