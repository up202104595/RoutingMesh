#!/bin/bash
# run_tests.sh — Automated RTT test sequence
# Run on Node 3 (base station) while rtt_test.py --mode server runs on Node 1
#
# Prerequisites:
#   Node 1: python3 tests/rtt_test.py --mode server
#   Node 1: python3 tests/throughput_test.py --mode server
#
# Usage: bash tests/run_tests.sh [direct|relay|both]

set -e
TOPOLOGY=${1:-"direct"}
N1_IP="10.0.0.1"
N2_IP="10.0.0.2"
RESULTS_DIR="tests/results/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$RESULTS_DIR"
cd "$RESULTS_DIR"

echo "=== RA-TDMAs+ Test Suite ==="
echo "  Topology: $TOPOLOGY"
echo "  Results:  $RESULTS_DIR"
echo ""

run_rtt() {
    local label=$1
    local target=$2
    local topo=$3
    echo "[RTT] $label → $target ($topo)"
    python3 ../../rtt_test.py \
        --mode client \
        --target "$target" \
        --count 100 \
        --interval 0.1 \
        --label "$label" \
        --topology "$topo"
    echo ""
}

run_thru() {
    local label=$1
    local target=$2
    local pktsize=$3
    local topo=$4
    echo "[THRU] $label pkt=${pktsize}B → $target ($topo)"
    python3 ../../throughput_test.py \
        --mode client \
        --target "$target" \
        --duration 10 \
        --pktsize "$pktsize" \
        --label "$label" \
        --topology "$topo"
    echo ""
}

if [[ "$TOPOLOGY" == "direct" || "$TOPOLOGY" == "both" ]]; then
    echo "--- DIRECT (N3 → N1 direct, no relay) ---"
    run_rtt "direct_N3toN1_100ms" "$N1_IP" "direct"
    run_rtt "direct_N3toN1_10ms"  "$N1_IP" "direct"  # change interval below if needed
    run_thru "direct_N3toN1_1316B"  "$N1_IP" 1316 "direct"
    run_thru "direct_N3toN1_512B"   "$N1_IP"  512 "direct"
    run_thru "direct_N3toN1_128B"   "$N1_IP"  128 "direct"
fi

if [[ "$TOPOLOGY" == "relay" || "$TOPOLOGY" == "both" ]]; then
    echo ""
    echo "--- RELAY (N3 → N2 → N1, Node 2 as relay) ---"
    echo "Make sure Node 1 is only reachable via Node 2 before continuing."
    read -p "Press Enter when topology is set to relay..."
    run_rtt "relay_N3toN1_100ms" "$N1_IP" "relay"
    run_thru "relay_N3toN1_1316B"  "$N1_IP" 1316 "relay"
    run_thru "relay_N3toN1_512B"   "$N1_IP"  512 "relay"
    run_thru "relay_N3toN1_128B"   "$N1_IP"  128 "relay"
fi

echo ""
echo "=== Generating summary table ==="
python3 ../../results_summary.py --dir .

echo ""
echo "Done. Results in: $RESULTS_DIR"
