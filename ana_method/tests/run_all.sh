#!/usr/bin/env bash
# =============================================================================
#  run_all.sh — Suite COMPLETA de métricas para o método Ana (meshnode_ana)
#
#  Mede o MESMO que a suite do método Miguel, para comparação directa:
#    FASE 0  captura STATE packets  -> análise de colocação por slot
#    FASE 1  link DIRETO : RTT + throughput + timing TDMA   (x RUNS)
#    FASE 2  RELAY       : convergência + throughput + timing TDMA (x RUNS)
#    FASE 3  resumo
#
#  Corre INTEIRAMENTE no N3 (base station). Pré-requisitos:
#    - mesh ana ativa nos 3 nós:  sudo ./meshnode_ana <id> 3
#    - vídeo a fluir N1 -> 10.0.0.3:5000
#    - no N1:  python3 tests/rtt_test.py --mode server &
#
#  Uso:
#    sudo bash tests/run_all.sh                      # 3 runs, com relay
#    sudo bash tests/run_all.sh --runs 5
#    sudo bash tests/run_all.sh --no-relay
#    sudo bash tests/run_all.sh --node1 172.20.10.1 --node1-phy 172.20.10.1 --iface wlan0
# =============================================================================
set -uo pipefail

RUNS=3
DO_RELAY=true
NODE1_IP="10.0.0.1"
NODE1_PHY="172.20.10.1"
IFACE="wlan0"
CAP_SECS=60
TDMA_DURATION=30
TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESULTS_DIR="${TESTS_DIR}/results_ana_$(date +%Y%m%d_%H%M%S)"

while [[ $# -gt 0 ]]; do
  case $1 in
    --runs)      RUNS="$2";      shift 2 ;;
    --no-relay)  DO_RELAY=false; shift ;;
    --node1)     NODE1_IP="$2";  shift 2 ;;
    --node1-phy) NODE1_PHY="$2"; shift 2 ;;
    --iface)     IFACE="$2";     shift 2 ;;
    --cap-secs)  CAP_SECS="$2";  shift 2 ;;
    *) echo "arg desconhecido: $1"; exit 1 ;;
  esac
done

mkdir -p "$RESULTS_DIR"; cd "$RESULTS_DIR"
G='\033[0;32m'; Y='\033[1;33m'; N='\033[0m'
info() { echo -e "${G}[INFO]${N} $*"; }
warn() { echo -e "${Y}[WARN]${N} $*"; }
sep()  { echo -e "${Y}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${N}"; }

block_link()   { iptables -I INPUT 1 -s "$NODE1_PHY" -j DROP 2>/dev/null || true
                 iptables -I OUTPUT 1 -d "$NODE1_PHY" -j DROP 2>/dev/null || true; }
restore_link() { iptables -D INPUT -s "$NODE1_PHY" -j DROP 2>/dev/null || true
                 iptables -D OUTPUT -d "$NODE1_PHY" -j DROP 2>/dev/null || true; }
_cleanup() { echo; warn "interrompido — a restaurar iptables"; restore_link; exit 1; }
trap _cleanup INT TERM
reachable() { ping -c1 -W1 "$NODE1_IP" &>/dev/null; }

echo "╔════════════════════════════════════════════════════════╗"
echo "║  Método Ana — Suite completa de métricas                ║"
echo "╚════════════════════════════════════════════════════════╝"
info "node1=$NODE1_IP / $NODE1_PHY   iface=$IFACE   runs=$RUNS   relay=$DO_RELAY"
info "resultados: $RESULTS_DIR"
echo "  Confirma no N1:  python3 tests/rtt_test.py --mode server &"
sep

# ── FASE 0 — captura de STATE packets para análise de slot ────────────────────
info "FASE 0 — captura de STATE packets (${CAP_SECS}s) em background"
if command -v tcpdump >/dev/null; then
  ( timeout "$CAP_SECS" tcpdump -i "$IFACE" -w state.pcap 'udp portrange 7001-7003' 2>/dev/null ) &
  CAP_PID=$!
  info "tcpdump a capturar -> state.pcap (pid $CAP_PID)"
else
  warn "tcpdump ausente — captura manualmente no Wireshark: udp portrange 7001-7003"
fi

# ── FASE 1 — LINK DIRETO ──────────────────────────────────────────────────────
echo; sep; info "FASE 1 — LINK DIRETO (RTT + throughput + timing)"; sep
for run in $(seq 1 "$RUNS"); do
  echo; info "── run $run/$RUNS (direto) ──"
  info "RTT direto..."
  python3 "$TESTS_DIR/rtt_test.py" --mode client --target "$NODE1_IP" \
      --count 100 --interval 0.1 --topology direct --label "direct_rtt_r${run}"
  info "throughput direto (15s)..."
  python3 "$TESTS_DIR/throughput_test.py" --duration 15 --topology direct \
      --label "direct_thru_r${run}"
  info "timing TDMA direto (${TDMA_DURATION}s)..."
  python3 "$TESTS_DIR/tdma_timing_test.py" --duration "$TDMA_DURATION" \
      --label "direct_r${run}"
  sleep 2
done

if [[ "$DO_RELAY" == "true" ]]; then
  # ── FASE 2 — RELAY ──────────────────────────────────────────────────────────
  echo; sep; info "FASE 2 — RELAY  N1->N2->N3 (convergência + throughput + timing)"; sep
  for run in $(seq 1 "$RUNS"); do
    echo; info "── run $run/$RUNS (relay) ──"
    info "convergência (bloqueia/restaura link)..."
    python3 "$TESTS_DIR/convergence_test.py" --label "conv_r${run}" --node1-phy "$NODE1_PHY"

    info "a bloquear link para medir em relay..."
    block_link; sleep 5
    info "throughput relay (15s)..."
    python3 "$TESTS_DIR/throughput_test.py" --duration 15 --topology relay \
        --label "relay_thru_r${run}"
    info "timing TDMA relay (${TDMA_DURATION}s)..."
    python3 "$TESTS_DIR/tdma_timing_test.py" --duration "$TDMA_DURATION" \
        --label "relay_r${run}"
    info "a restaurar link e aguardar node-aging (~10s)..."
    restore_link
    for i in $(seq 1 20); do reachable && break; sleep 1; done
    sleep 10
  done
fi

# ── FASE 3 — resumo ───────────────────────────────────────────────────────────
echo; sep; info "FASE 3 — RESUMO"; sep
wait 2>/dev/null || true   # espera o tcpdump terminar
[[ -f state.pcap ]] && info "captura de slots -> $RESULTS_DIR/state.pcap"
python3 - "$RESULTS_DIR" <<'PY'
import sys, glob, json, statistics as st
d = sys.argv[1]
def load(p):
    try: return json.load(open(p))
    except: return {}
conv=[load(f).get("convergence_ms") for f in glob.glob(f"{d}/convergence_*.json")]
conv=[c for c in conv if c]
rtt =[load(f) for f in glob.glob(f"{d}/rtt_results_*.json")]
thr =[load(f) for f in glob.glob(f"{d}/throughput_*.json")]
print("\n  CONVERGÊNCIA:")
if conv: print(f"    mediana {st.median(conv):.0f} ms  (min {min(conv):.0f}/max {max(conv):.0f}, n={len(conv)})")
else:    print("    sem gaps medidos (relay quente)")
def avg(rows,k):
    v=[r.get(k) for r in rows if r.get(k) is not None]
    return st.mean(v) if v else None
for topo in ("direct","relay"):
    rr=[r for r in rtt if r.get("topology")==topo]
    tt=[t for t in thr if t.get("topology")==topo]
    if rr: print(f"  RTT {topo:>6}: avg {avg(rr,'avg_ms'):.1f} ms  PDR {avg(rr,'pdr_pct'):.0f}%  (n={len(rr)})")
    if tt: print(f"  THR {topo:>6}: {avg(tt,'throughput_kbps'):.0f} kbps  (n={len(tt)})")
PY
echo; info "JSON + state.pcap em: $RESULTS_DIR"
info "Análise de slots: exporta state.pcap -> state.csv e corre"
info "  python3 $TESTS_DIR/slot_occupancy.py state.csv --out figs/ana_slots --phy-prefix ${NODE1_PHY%.*}"
