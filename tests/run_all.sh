#!/usr/bin/env bash
# =============================================================================
#  run_all.sh — Suite completa de métricas RA-TDMAs+
#
#  Corre INTEIRAMENTE no Nó 3 (base station / PC).
#
#  Preparação no Nó 1 (robot) antes de começar:
#    python3 tests/rtt_test.py --mode server &
#
#  Uso:
#    sudo bash tests/run_all.sh                  # defaults (3 runs, com relay)
#    sudo bash tests/run_all.sh --runs 5
#    sudo bash tests/run_all.sh --no-relay
#    sudo bash tests/run_all.sh --node1 10.0.0.1
# =============================================================================

set -uo pipefail

NODE1_IP="10.0.0.1"
NODE1_PHY="172.20.10.1"
RUNS=3
DO_RELAY=true
TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESULTS_DIR="${TESTS_DIR}/results_$(date +%Y%m%d_%H%M%S)"
TDMA_DURATION=30   # segundos de análise de timing TDMA

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
sep()   { echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; }
wait_enter() { read -r -p "  Prima ENTER quando pronto..."; echo ""; }

check_reachable() { ping -c 1 -W 1 "$NODE1_IP" &>/dev/null; }

wait_reachable() {
    info "A aguardar que $NODE1_IP fique acessível..."
    for i in $(seq 1 30); do
        if check_reachable; then info "Nó 1 acessível."; return 0; fi
        sleep 1
    done
    warn "Nó 1 não responde após 30s — a continuar"
}

block_link() {
    iptables -I INPUT  1 -s "$NODE1_PHY" -j DROP 2>/dev/null || true
    iptables -I OUTPUT 1 -d "$NODE1_PHY" -j DROP 2>/dev/null || true
    info "Link direto bloqueado ($NODE1_PHY)"
}

restore_link() {
    iptables -D INPUT  -s "$NODE1_PHY" -j DROP 2>/dev/null || true
    iptables -D OUTPUT -d "$NODE1_PHY" -j DROP 2>/dev/null || true
    info "Link direto restaurado"
}

# ── banner ────────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  RA-TDMAs+ — Suite de Métricas para Tese                    ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
info "Nó 1 (robot): $NODE1_IP / $NODE1_PHY"
info "Repetições:   $RUNS"
info "Relay:        $DO_RELAY"
info "Resultados:   $RESULTS_DIR"
echo ""

echo "  Confirma que no Nó 1 está a correr:"
echo "    python3 tests/rtt_test.py --mode server &"
sep
wait_enter

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
echo "  FASE 1 — LINK DIRETO"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

for run in $(seq 1 "$RUNS"); do
    echo ""
    info "── Run $run/$RUNS ──────────────────────────────────"

    info "RTT direto (N3 -> N1)..."
    python3 "$TESTS_DIR/rtt_test.py" \
        --mode client --target "$NODE1_IP" \
        --count 100 --interval 0.1 \
        --topology direct \
        --label "direct_rtt_r${run}"

    echo ""
    info "Throughput direto — a medir vídeo existente 15s..."
    python3 "$TESTS_DIR/throughput_test.py" \
        --duration 15 --topology direct \
        --label "direct_thru_r${run}"

    echo ""
    info "Timing TDMA direto — a analisar inter-arrivals ${TDMA_DURATION}s..."
    python3 "$TESTS_DIR/tdma_timing_test.py" \
        --duration "$TDMA_DURATION" \
        --label "direct_r${run}"

    sleep 2
done

if [[ "$DO_RELAY" == "false" ]]; then
    python3 "$TESTS_DIR/results_summary.py" --dir "$RESULTS_DIR"
    info "Concluido. Resultados em: $RESULTS_DIR"
    exit 0
fi

# ══════════════════════════════════════════════════════════════════════════════
#  FASE 2 — CONVERGÊNCIA + RELAY
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  FASE 2 — RELAY  (N1 -> N2 -> N3)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

for run in $(seq 1 "$RUNS"); do
    echo ""
    info "── Run $run/$RUNS ──────────────────────────────────"

    # convergence_test bloqueia o link internamente e restaura no fim
    info "Convergência (bloqueia/restaura link automaticamente)..."
    python3 "$TESTS_DIR/convergence_test.py" \
        --label "conv_r${run}"

    # após convergence_test o link já foi restaurado — bloquear de novo
    # para medir throughput e timing em modo relay
    info "A bloquear link para medições em relay..."
    block_link
    sleep 5   # aguarda relay estabilizar

    echo ""
    info "Throughput relay — a medir vídeo via relay 15s..."
    python3 "$TESTS_DIR/throughput_test.py" \
        --duration 15 --topology relay \
        --label "relay_thru_r${run}"

    echo ""
    info "Timing TDMA relay — a analisar inter-arrivals ${TDMA_DURATION}s..."
    python3 "$TESTS_DIR/tdma_timing_test.py" \
        --duration "$TDMA_DURATION" \
        --label "relay_r${run}"

    info "A restaurar link direto e aguardar hysteresis (10s)..."
    restore_link
    wait_reachable
    sleep 10
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
