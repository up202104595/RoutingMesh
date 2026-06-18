#!/usr/bin/env bash
# run_tests.sh — Wrapper rápido para testes individuais (sem relay automático)
#
# Uso:
#   bash tests/run_tests.sh direct     # só fase directa
#   bash tests/run_tests.sh relay      # só medições em modo relay (já activo)
#   bash tests/run_tests.sh both       # directo + relay (pede confirmação)
#
# Pré-requisito: no Nó 1 correr:
#   python3 tests/rtt_test.py --mode server &
#
# Para a suite completa com convergência automática usar run_all.sh.

set -uo pipefail

TOPOLOGY=${1:-"direct"}
NODE1_IP="10.0.0.1"
RUNS=2
DURATION_THRU=15
DURATION_TDMA=30
TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESULTS_DIR="${TESTS_DIR}/results_quick_$(date +%Y%m%d_%H%M%S)"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info() { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }

mkdir -p "$RESULTS_DIR"
cd "$RESULTS_DIR"

info "Resultados em: $RESULTS_DIR"

run_direct() {
    local r=$1
    info "── RTT directo run $r ──"
    python3 "$TESTS_DIR/rtt_test.py" \
        --mode client --target "$NODE1_IP" \
        --count 100 --interval 0.1 \
        --topology direct --label "direct_rtt_r${r}"

    info "── Throughput directo run $r ──"
    python3 "$TESTS_DIR/throughput_test.py" \
        --duration "$DURATION_THRU" --topology direct \
        --label "direct_thru_r${r}"

    info "── Timing TDMA directo run $r ──"
    python3 "$TESTS_DIR/tdma_timing_test.py" \
        --duration "$DURATION_TDMA" --label "direct_r${r}"
}

run_relay() {
    local r=$1
    info "── RTT relay run $r ──"
    python3 "$TESTS_DIR/rtt_test.py" \
        --mode client --target "$NODE1_IP" \
        --count 100 --interval 0.1 \
        --topology relay --label "relay_rtt_r${r}"

    info "── Throughput relay run $r ──"
    python3 "$TESTS_DIR/throughput_test.py" \
        --duration "$DURATION_THRU" --topology relay \
        --label "relay_thru_r${r}"

    info "── Timing TDMA relay run $r ──"
    python3 "$TESTS_DIR/tdma_timing_test.py" \
        --duration "$DURATION_TDMA" --label "relay_r${r}"
}

case "$TOPOLOGY" in
direct)
    for r in $(seq 1 "$RUNS"); do run_direct "$r"; done
    ;;
relay)
    warn "Certifica que o relay está activo (link directo bloqueado ou fora de alcance)"
    read -r -p "  Prima ENTER quando pronto..."
    for r in $(seq 1 "$RUNS"); do run_relay "$r"; done
    ;;
both)
    for r in $(seq 1 "$RUNS"); do run_direct "$r"; done
    echo ""
    warn "Configura agora o modo relay (bloqueia link directo ou afasta N1)"
    read -r -p "  Prima ENTER quando relay estiver activo..."
    for r in $(seq 1 "$RUNS"); do run_relay "$r"; done
    ;;
*)
    echo "Uso: $0 [direct|relay|both]"; exit 1 ;;
esac

echo ""
info "A gerar sumário..."
python3 "$TESTS_DIR/results_summary.py" --dir "$RESULTS_DIR"
info "Concluído. Resultados em: $RESULTS_DIR"
