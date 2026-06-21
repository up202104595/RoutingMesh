#!/usr/bin/env bash
# =============================================================================
#  run_all.sh — Suite de métricas para o método Ana (meshnode_ana)
#
#  Mede o MESMO que a suite do método Miguel, para comparação directa:
#    • Tempo de convergência do relay (interrupção do vídeo)  [N rondas]
#    • Captura dos STATE packets para a análise de colocação por slot
#
#  Corre INTEIRAMENTE no N3 (base station). Pré-requisitos:
#    - mesh ana ativa nos 3 nós  (sudo ./meshnode_ana <id> 3)
#    - vídeo a fluir N1 -> 10.0.0.3:5000  (mesma app de teste do método Miguel)
#
#  Uso:
#    sudo bash tests/run_all.sh                 # 3 runs de convergência + captura
#    sudo bash tests/run_all.sh --runs 5
#    sudo bash tests/run_all.sh --node1-phy 172.20.10.1 --iface wlan0
# =============================================================================
set -uo pipefail

RUNS=3
NODE1_PHY="172.20.10.1"
IFACE="wlan0"
CAP_SECS=60
TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESULTS_DIR="${TESTS_DIR}/results_ana_$(date +%Y%m%d_%H%M%S)"

while [[ $# -gt 0 ]]; do
  case $1 in
    --runs)      RUNS="$2";      shift 2 ;;
    --node1-phy) NODE1_PHY="$2"; shift 2 ;;
    --iface)     IFACE="$2";     shift 2 ;;
    --cap-secs)  CAP_SECS="$2";  shift 2 ;;
    *) echo "arg desconhecido: $1"; exit 1 ;;
  esac
done

mkdir -p "$RESULTS_DIR"; cd "$RESULTS_DIR"
G='\033[0;32m'; Y='\033[1;33m'; N='\033[0m'
info() { echo -e "${G}[INFO]${N} $*"; }

_cleanup() {
  echo; info "interrompido — a restaurar iptables"
  iptables -D INPUT  -s "$NODE1_PHY" -j DROP 2>/dev/null || true
  iptables -D OUTPUT -d "$NODE1_PHY" -j DROP 2>/dev/null || true
  exit 1
}
trap _cleanup INT TERM

echo "╔════════════════════════════════════════════════════════╗"
echo "║  Método Ana — Suite de métricas (convergência + slots) ║"
echo "╚════════════════════════════════════════════════════════╝"
info "node1_phy=$NODE1_PHY  iface=$IFACE  runs=$RUNS"
info "resultados: $RESULTS_DIR"

# ── FASE 1: captura dos STATE packets para análise de slots ───────────────────
echo; info "FASE 1 — captura de STATE packets (${CAP_SECS}s) para análise de slot"
if command -v tcpdump >/dev/null; then
  timeout "$CAP_SECS" tcpdump -i "$IFACE" -w state.pcap 'udp portrange 7001-7003' 2>/dev/null || true
  info "captura guardada -> state.pcap"
  info "exporta para CSV (Wireshark) e corre:"
  info "  python3 $TESTS_DIR/slot_occupancy.py state.csv --out ana_slots --phy-prefix ${NODE1_PHY%.*}"
else
  info "tcpdump ausente — captura manualmente no Wireshark: udp portrange 7001-7003"
fi

# ── FASE 2: convergência do relay ─────────────────────────────────────────────
echo; info "FASE 2 — convergência do relay (${RUNS} runs)"
for run in $(seq 1 "$RUNS"); do
  echo; info "── run $run/$RUNS ──"
  python3 "$TESTS_DIR/convergence_test.py" --label "conv_r${run}" --node1-phy "$NODE1_PHY"
  info "a aguardar hysteresis do node-aging (restabelecer link, ~3s)"
  sleep 5
done

# ── resumo ────────────────────────────────────────────────────────────────────
echo; info "FASE 3 — resumo da convergência"
python3 - "$RESULTS_DIR" <<'PY'
import sys, glob, json, statistics
d = sys.argv[1]
vals = []
for f in sorted(glob.glob(f"{d}/convergence_*.json")):
    r = json.load(open(f))
    cm = r.get("convergence_ms")
    tag = f"{cm} ms" if cm else "sem gap (relay quente / instantâneo)"
    print(f"  {r['label']:>10}: {tag}")
    if cm: vals.append(cm)
if vals:
    print(f"\n  mediana: {statistics.median(vals):.0f} ms   "
          f"(min {min(vals):.0f} / max {max(vals):.0f}, n={len(vals)})")
PY
echo; info "JSON em: $RESULTS_DIR"
