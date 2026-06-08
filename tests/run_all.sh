#!/usr/bin/env bash
# =============================================================================
#  run_all.sh — Suite completa de métricas RA-TDMAs+
#
#  Corre INTEIRAMENTE no Nó 3 (base station / PC).
#
#  Preparação no Nó 1 (robot) — arrancar servidores RTT:
#    python3 tests/rtt_test.py --mode server &
#
#  Uso:
#    bash tests/run_all.sh                  # defaults (3 runs, com relay)
#    bash tests/run_all.sh --runs 5         # 5 repetições
#    bash tests/run_all.sh --no-relay       # só métricas direto
#    bash tests/run_all.sh --node1 10.0.0.1 # IP do robot (default)
#
#  Sequência:
#    FASE 1 — Link direto
#      1a. RTT N3→N1 (100 pings)
#      1b. Throughput N1→N3 (servidor no PC, pausa p/ correr cliente no Nó 1)
#    FASE 2 — Relay (repetido RUNS vezes)
#      2a. Pausa: bloquear link N1↔N3 com iptables no Nó 1
#      2b. Convergência automática
#      2c. RTT via relay
#      2d. Throughput via relay (servidor no PC, pausa p/ correr cliente no Nó 1)
#      2e. Pausa: restaurar link
#    FASE 3 — Sumário final
# =============================================================================

set -euo pipefail

NODE1_IP="10.0.0.1"
RUNS=3
DO_RELAY=true
TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESULTS_DIR="${TESTS_DIR}/results_$(date +%Y%m%d_%H%M%S)"

while [[ $# -gt 0 ]]; do
    case $1 in
        --node1)    NODE1_IP="$2"; shift 2 ;;
        --runs)     RUNS="$2";     shift 2 ;;
        --no-relay) DO_RELAY=false; shift ;;
        *) echo "Argumento desconhecido: $1"; exit 1 ;;
    esac
done

mkdir -p "$RESULTS_DIR"
cd "$RESULTS_DIR"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }

pause() {
    echo ""
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}  AÇÃO NECESSÁRIA:${NC}"
    echo ""
    echo -e "    $*"
    echo ""
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    read -r -p "  Prima ENTER quando pronto..."
    echo ""
}

check_reachable() { ping -c 1 -W 1 "$NODE1_IP" &>/dev/null; }

wait_reachable() {
    info "A aguardar que $NODE1_IP fique acessível..."
    for i in $(seq 1 30); do
        if check_reachable; then info "Nó 1 acessível."; return 0; fi
        sleep 1
    done
    warn "Nó 1 não responde após 30s — a continuar"
}

# throughput_server: corre servidor em background, aguarda conclusão
# uso: throughput_server <label> <topology>
throughput_server() {
    local label="$1" topo="$2"
    python3 "$TESTS_DIR/throughput_test.py" \
        --mode server \
        --label "$label" \
        --topology "$topo"
}

# ── banner ────────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  RA-TDMAs+ — Suite de Métricas para Tese                    ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
info "Nó 1 (robot): $NODE1_IP"
info "Repetições:   $RUNS"
info "Relay:        $DO_RELAY"
info "Resultados:   $RESULTS_DIR"
echo ""

pause "Confirma que no Nó 1 está a correr:
  python3 tests/rtt_test.py --mode server &
  (o servidor de throughput NÃO é necessário no Nó 1)"

info "A verificar conectividade com Nó 1..."
if ! check_reachable; then
    warn "Nó 1 não responde. Verifica se a mesh está ativa."
    wait_reachable
fi
info "Conectividade OK."

# ══════════════════════════════════════════════════════════════════════════════
#  FASE 1 — LINK DIRETO
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  FASE 1 — LINK DIRETO  (N1 → N3,  N3 → N1 para RTT)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

for run in $(seq 1 "$RUNS"); do
    info "── Run $run/$RUNS ──────────────────────────────────"

    info "RTT direto (N3 → N1)"
    python3 "$TESTS_DIR/rtt_test.py" \
        --mode client --target "$NODE1_IP" \
        --count 100 --interval 0.1 \
        --topology direct \
        --label "direct_rtt_r${run}"

    echo ""

    # throughput 1316B
    pause "THROUGHPUT DIRETO 1316B — run $run/$RUNS
No Nó 1, executa AGORA (o servidor aqui fica à escuta 20s):
  python3 tests/throughput_test.py --mode client --target 10.0.0.3 --pktsize 1316 --duration 15"

    info "Servidor de throughput direto 1316B a escutar... (aguarda dados do Nó 1)"
    throughput_server "direct_thru_1316_r${run}" "direct"

    echo ""

    # throughput 512B
    pause "THROUGHPUT DIRETO 512B — run $run/$RUNS
No Nó 1, executa AGORA:
  python3 tests/throughput_test.py --mode client --target 10.0.0.3 --pktsize 512 --duration 15"

    info "Servidor de throughput direto 512B a escutar..."
    throughput_server "direct_thru_512_r${run}" "direct"

    echo ""
    sleep 2
done

if [[ "$DO_RELAY" == "false" ]]; then
    python3 "$TESTS_DIR/results_summary.py" --dir "$RESULTS_DIR"
    info "Concluído. Resultados em: $RESULTS_DIR"
    exit 0
fi

# ══════════════════════════════════════════════════════════════════════════════
#  FASE 2 — CONVERGÊNCIA + RELAY
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  FASE 2 — RELAY  (N1 → N2 → N3)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

for run in $(seq 1 "$RUNS"); do
    info "── Run $run/$RUNS ──────────────────────────────────"

    pause "BLOQUEAR LINK DIRETO — run $run/$RUNS
No Nó 1, executa:
  sudo iptables -A INPUT  -s 172.20.10.3 -j DROP
  sudo iptables -A OUTPUT -d 172.20.10.3 -j DROP"

    info "A testar convergência — aguarda relay ativar automaticamente..."
    python3 "$TESTS_DIR/convergence_test.py" \
        --target "$NODE1_IP" \
        --label "conv_r${run}" \
        --duration 60 \
        --interval 0.1

    echo ""
    info "RTT relay (N3 → N1 via N2)"
    python3 "$TESTS_DIR/rtt_test.py" \
        --mode client --target "$NODE1_IP" \
        --count 100 --interval 0.15 \
        --topology relay \
        --label "relay_rtt_r${run}"

    echo ""

    # throughput relay 1316B
    pause "THROUGHPUT RELAY 1316B — run $run/$RUNS
No Nó 1, executa AGORA:
  python3 tests/throughput_test.py --mode client --target 10.0.0.3 --pktsize 1316 --duration 15"

    info "Servidor de throughput relay 1316B a escutar..."
    throughput_server "relay_thru_1316_r${run}" "relay"

    echo ""

    # throughput relay 512B
    pause "THROUGHPUT RELAY 512B — run $run/$RUNS
No Nó 1, executa AGORA:
  python3 tests/throughput_test.py --mode client --target 10.0.0.3 --pktsize 512 --duration 15"

    info "Servidor de throughput relay 512B a escutar..."
    throughput_server "relay_thru_512_r${run}" "relay"

    echo ""
    pause "RESTAURAR LINK DIRETO — run $run/$RUNS
No Nó 1, executa:
  sudo iptables -F"

    wait_reachable
    info "A aguardar hysteresis (10s)..."
    sleep 10
    echo ""
done

# ══════════════════════════════════════════════════════════════════════════════
#  FASE 3 — SUMÁRIO
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  FASE 3 — RESULTADOS FINAIS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

python3 "$TESTS_DIR/results_summary.py" --dir "$RESULTS_DIR"

echo ""
info "Todos os JSON em: $RESULTS_DIR"
info "Para rever: python3 tests/results_summary.py --dir $RESULTS_DIR"
echo ""
