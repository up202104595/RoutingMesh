#!/bin/bash
# tmux-node.sh — arranca o daemon do no EM SEGUNDO PLANO, sobrevivendo a quedas
# de SSH e a fechar o terminal.
#
# Uso (em CADA no, como root):
#     sudo ./tmux-node.sh <l3|arp> <node_id> [num_nodes=3]
#
# Dois modos (escolhido automaticamente):
#   * COM tmux: o no corre numa sessao tmux "mesh".
#       ver:     sudo tmux attach -t mesh        (sair sem parar: Ctrl+b, d)
#       espreitar: sudo tmux capture-pane -p -t mesh | tail -20
#       parar:   sudo tmux kill-session -t mesh
#   * SEM tmux (nao precisa de instalar nada): o no corre com nohup e a saida vai
#     para /tmp/mesh.log (no proprio no).
#       ver:     tail -f /tmp/mesh.log           (Ctrl+C so sai do tail)
#       espreitar: tail -20 /tmp/mesh.log
#       parar:   sudo pkill -KILL -f '[m]eshnode_'
#     Forcar este modo mesmo com tmux instalado:  NO_TMUX=1 sudo -E ./tmux-node.sh ...
#
# Se ja estiver um no a correr (de outro metodo, por exemplo) e substituido; o
# run-node.sh limpa o que ele deixou. Se o no terminar ou der erro, a mensagem e
# o codigo de saida ficam visiveis (na sessao tmux ou no fim do log).

usage() { echo "Uso: sudo $0 <l3|arp> <node_id> [num_nodes=3]"; exit 1; }

METHOD=${1:-}
ID=${2:-}
N=${3:-3}
SESSION=mesh
LOG=/tmp/mesh.log

case "$METHOD" in l3|arp) ;; *) usage ;; esac
[[ "$ID" =~ ^[0-9]+$ ]] || usage
[ "$EUID" -eq 0 ] || { echo "ERRO: corre com sudo (o run-node.sh precisa de root)"; exit 1; }

DIR="$(cd "$(dirname "$0")" && pwd)"
[ -x "$DIR/run-node.sh" ] || { echo "ERRO: $DIR/run-node.sh nao existe ou nao e executavel (chmod +x run-node.sh)"; exit 1; }

if [ "${NO_TMUX:-0}" != "1" ] && command -v tmux >/dev/null; then
    # ── modo tmux ─────────────────────────────────────────────────
    tmux kill-session -t "$SESSION" 2>/dev/null

    # A sessao fica aberta no fim (read), para as mensagens de erro nao se perderem.
    tmux new-session -d -s "$SESSION" -c "$DIR" \
      "./run-node.sh $METHOD $ID $N; rc=\$?; echo; echo \"--- o no terminou (codigo \$rc). Enter para fechar ---\"; read" \
      || { echo "ERRO: nao consegui criar a sessao tmux"; exit 1; }

    echo "[tmux-node] no $ID em $METHOD arrancado na sessao tmux '$SESSION'"
    echo "            ver:    sudo tmux attach -t $SESSION      (sair: Ctrl+b, d)"
    echo "            parar:  sudo tmux kill-session -t $SESSION"
else
    # ── modo sem tmux: nohup + log ────────────────────────────────
    command -v script >/dev/null || { echo "ERRO: sem tmux e sem o comando 'script' (util-linux)"; exit 1; }

    # termina um arranque anterior neste modo (o run-node.sh mata o daemon antigo)
    pkill -f '[s]cript -qfc ./run-node.sh' 2>/dev/null
    sleep 0.5

    # 'script' da ao daemon um pseudo-terminal: a saida chega ao log linha a linha
    # (sem ele ficava em buffer e o log atrasava-se).
    cd "$DIR" || exit 1
    setsid nohup script -qfc \
      "./run-node.sh $METHOD $ID $N; rc=\$?; echo; echo \"--- o no terminou (codigo \$rc) ---\"" \
      "$LOG" </dev/null >/dev/null 2>&1 &

    echo "[tmux-node] no $ID em $METHOD arrancado em segundo plano (sem tmux); log: $LOG"
    echo "            ver:    tail -f $LOG        (Ctrl+C so sai do tail)"
    echo "            parar:  sudo pkill -KILL -f '[m]eshnode_'"
fi
