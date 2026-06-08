#!/usr/bin/env bash
# =============================================================================
#  run_all.sh — Suite completa de métricas RA-TDMAs+
#
#  Corre no Nó 3 (base station / PC).
#  Requer que o Nó 1 (robot) tenha os servidores a correr:
#    python3 tests/rtt_test.py --mode server &
#    python3 tests/throughput_test.py --mode server &
#
#  Uso:
#    bash tests/run_all.sh                        # usa defaults
#    bash tests/run_all.sh --node1 10.0.0.1       # IP do robot (TUN)
#    bash tests/run_all.sh --runs 3               # repetições de cada teste
#    bash tests/run_all.sh --no-relay             # só métricas direto (sem relay)
#
#  Passos:
#    1. RTT direto (100 pings × 100ms)
#    2. Throughput direto (pkt=1316B, 15s)
#    3. Pausa — operador bloqueia link N1↔N3 com iptables no Nó 1
#    4. Teste de convergência (deteta automaticamente quando relay ativa)
#    5. RTT via relay (100 pings)
#    6. Throughput via relay (pkt=1316B, 15s)
#    7. Pausa — operador restaura link no Nó 1
#    8. Repete RUNS vezes para estatísticas
#    9. Gera tabela final com results_summary.py
# =============================================================================

set -euo pipefail

# ── defaults ──────────────────────────────────────────────────────────────────
NODE1_IP="10.0.0.1"
RUNS=3
DO_RELAY=true
RESULTS_DIR="$(dirname "$0")/results_$(date +%Y%m%d_%H%M%S)"
TESTS_DIR="$(dirname "$0")"

# ── parse args ────────────────────────────────────────────────────────────────
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

# ── helpers ───────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
pause() {
    echo ""
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}  AÇÃO NECESSÁRIA: $*${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    read -r -p "  Prima ENTER quando pronto..."
    echo ""
}

check_reachable() {
    if ping -c 1 -W 1 "$NODE1_IP" &>/dev/null; then
        return 0
    else
        return 1
    fi
}

wait_reachable() {
    info "A aguardar que $NODE1_IP fique acessível..."
    for i in $(seq 1 30); do
        if check_reachable; then
            info "Nó 1 acessível."
            return 0
        fi
        sleep 1
    done
    warn "Nó 1 não responde após 30s — a continuar na mesma"
}

wait_unreachable() {
    info "A aguardar que $NODE1_IP fique inacessível (link bloqueado)..."
    for i in $(seq 1 30); do
        if ! ping -c 1 -W 1 "$NODE1_IP" &>/dev/null 2>&1; then
            info "Link direto bloqueado."
            return 0
        fi
        sleep 1
    done
    warn "Nó 1 ainda acessível após 30s — relay pode não ser testado corretamente"
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

# ── verificar conectividade inicial ──────────────────────────────────────────
info "A verificar conectividade com Nó 1..."
if ! check_reachable; then
    warn "Nó 1 ($NODE1_IP) não responde. Verifica se a mesh está ativa."
    pause "Confirma que o meshnode está a correr no Nó 1 e Nó 2, depois prime ENTER"
    wait_reachable
fi
info "Conectividade OK."
echo ""

# ══════════════════════════════════════════════════════════════════════════════
#  FASE 1 — DIRETO
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  FASE 1 — MÉTRICAS COM LINK DIRETO (N3 ↔ N1)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

for run in $(seq 1 "$RUNS"); do
    info "RTT direto — run $run/$RUNS"
    python3 "$TESTS_DIR/rtt_test.py" \
        --mode client \
        --target "$NODE1_IP" \
        --count 100 \
        --interval 0.1 \
        --topology direct \
        --label "direct_rtt_r${run}"

    echo ""
    info "Throughput direto (1316B) — run $run/$RUNS"
    python3 "$TESTS_DIR/throughput_test.py" \
        --mode client \
        --target "$NODE1_IP" \
        --duration 15 \
        --pktsize 1316 \
        --topology direct \
        --label "direct_thru_1316_r${run}"

    echo ""
    info "Throughput direto (512B) — run $run/$RUNS"
    python3 "$TESTS_DIR/throughput_test.py" \
        --mode client \
        --target "$NODE1_IP" \
        --duration 15 \
        --pktsize 512 \
        --topology direct \
        --label "direct_thru_512_r${run}"

    echo ""
    sleep 2
done

if [[ "$DO_RELAY" == "false" ]]; then
    info "Relay desativado (--no-relay). A gerar sumário..."
    python3 "$TESTS_DIR/results_summary.py" --dir "$RESULTS_DIR"
    info "Concluído. Resultados em: $RESULTS_DIR"
    exit 0
fi

# ══════════════════════════════════════════════════════════════════════════════
#  FASE 2 — CONVERGÊNCIA + RELAY
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  FASE 2 — CONVERGÊNCIA E RELAY (N3 → N2 → N1)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

for run in $(seq 1 "$RUNS"); do
    echo ""
    info "=== Teste de convergência + relay — run $run/$RUNS ==="
    echo ""
    pause "No Nó 1, executa:
  sudo iptables -A INPUT  -s 172.20.10.3 -j DROP
  sudo iptables -A OUTPUT -d 172.20.10.3 -j DROP
Depois prime ENTER para iniciar o teste de convergência."

    info "A iniciar teste de convergência (run $run)..."
    info "O script vai detetar automaticamente quando o relay ativar."
    echo ""

    python3 "$TESTS_DIR/convergence_test.py" \
        --target "$NODE1_IP" \
        --label "conv_r${run}" \
        --duration 90 \
        --interval 0.1

    echo ""
    info "Convergência registada. A medir RTT e throughput via relay..."
    echo ""

    info "RTT relay — run $run/$RUNS"
    python3 "$TESTS_DIR/rtt_test.py" \
        --mode client \
        --target "$NODE1_IP" \
        --count 100 \
        --interval 0.1 \
        --topology relay \
        --label "relay_rtt_r${run}"

    echo ""
    info "Throughput relay (1316B) — run $run/$RUNS"
    python3 "$TESTS_DIR/throughput_test.py" \
        --mode client \
        --target "$NODE1_IP" \
        --duration 15 \
        --pktsize 1316 \
        --topology relay \
        --label "relay_thru_1316_r${run}"

    echo ""
    info "Throughput relay (512B) — run $run/$RUNS"
    python3 "$TESTS_DIR/throughput_test.py" \
        --mode client \
        --target "$NODE1_IP" \
        --duration 15 \
        --pktsize 512 \
        --topology relay \
        --label "relay_thru_512_r${run}"

    echo ""
    pause "No Nó 1, restaura o link:
  sudo iptables -F
Depois prime ENTER e aguarda o relay libertar (hysteresis ~8s)."

    wait_reachable
    info "A aguardar hysteresis (10s)..."
    sleep 10
    echo ""
done

# ══════════════════════════════════════════════════════════════════════════════
#  FASE 3 — SUMÁRIO
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  FASE 3 — RESULTADOS FINAIS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

python3 "$TESTS_DIR/results_summary.py" --dir "$RESULTS_DIR"

echo ""
info "Todos os JSON guardados em: $RESULTS_DIR"
info "Para ver de novo: python3 tests/results_summary.py --dir $RESULTS_DIR"
echo ""
