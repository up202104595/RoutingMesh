#!/usr/bin/env python3
"""
results_summary.py — Aggregate and display all test results in thesis table format

Usage:
  python3 results_summary.py               # reads all JSON files in current dir
  python3 results_summary.py --dir /path   # reads from specific directory

Produces tables comparable to the previous thesis (Table 4.2 / Table 4.4):
  - RTT statistics per topology
  - Convergence time summary
  - Throughput per packet size and topology
"""

import json
import glob
import argparse
import os
import statistics

def load_json_files(pattern):
    files = glob.glob(pattern)
    results = []
    for f in files:
        try:
            with open(f) as fh:
                results.append(json.load(fh))
        except Exception as e:
            print(f"  WARN: could not read {f}: {e}")
    return results

def table_rtt(results):
    if not results:
        print("  (no RTT results found)")
        return

    print("\n┌─────────────────────────────────────────────────────────────────────┐")
    print("│  RTT Results — RA-TDMAs+ Mesh                                       │")
    print("├────────────────────────┬───────┬───────┬───────┬───────┬────────────┤")
    print("│  Label                 │  Avg  │  Min  │  Max  │  Std  │  Jitter    │")
    print("│                        │  (ms) │  (ms) │  (ms) │  (ms) │  (ms)      │")
    print("├────────────────────────┼───────┼───────┼───────┼───────┼────────────┤")

    for r in sorted(results, key=lambda x: x.get("label","")):
        lbl = r.get("label", "?")[:24]
        print(f"│  {lbl:<22}  │ {r['avg_ms']:>5.2f} │ {r['min_ms']:>5.2f} "
              f"│ {r['max_ms']:>5.2f} │ {r['std_ms']:>5.2f} │ {r['jitter_ms']:>7.3f}    │")

    print("└────────────────────────┴───────┴───────┴───────┴───────┴────────────┘")

def table_convergence(results):
    if not results:
        print("  (no convergence results found)")
        return

    print("\n┌──────────────────────────────────────────────────────────┐")
    print("│  Topology Convergence Times — RA-TDMAs+                  │")
    print("├───────────────────┬─────────────┬────────────┬───────────┤")
    print("│  Label            │  Conv.(ms)  │  RTT_bef.  │  RTT_aft. │")
    print("├───────────────────┼─────────────┼────────────┼───────────┤")

    for r in sorted(results, key=lambda x: x.get("label","")):
        lbl   = r.get("label","?")[:19]
        conv  = r.get("convergence_ms")
        conv_s = f"{conv:.0f}" if conv else "N/A"
        bef   = r.get("rtt_before",{}).get("avg_ms","?")
        aft   = r.get("rtt_after", {}).get("avg_ms","?")
        bef_s = f"{bef:.2f}" if isinstance(bef, float) else "?"
        aft_s = f"{aft:.2f}" if isinstance(aft, float) else "?"
        print(f"│  {lbl:<17}  │ {conv_s:>11}  │ {bef_s:>10} │ {aft_s:>9} │")

    print("└───────────────────┴─────────────┴────────────┴───────────┘")

def table_throughput(results):
    if not results:
        print("  (no throughput results found)")
        return

    print("\n┌────────────────────────────────────────────────────────┐")
    print("│  UDP Throughput Results — RA-TDMAs+                    │")
    print("├───────────────────┬──────────┬──────────┬──────────────┤")
    print("│  Label            │  PktSize │  Topology│  Kbps (sent) │")
    print("├───────────────────┼──────────┼──────────┼──────────────┤")

    for r in sorted(results, key=lambda x: x.get("label","")):
        lbl  = r.get("label","?")[:19]
        psz  = r.get("pkt_size_bytes","?")
        topo = r.get("topology","?")[:8]
        kbps = r.get("throughput_kbps","?")
        kbps_s = f"{kbps:.1f}" if isinstance(kbps, float) else "?"
        print(f"│  {lbl:<17}  │ {str(psz):>8} │ {topo:>8} │ {kbps_s:>12} │")

    print("└───────────────────┴──────────┴──────────┴──────────────┘")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default=".", help="Directory with result JSON files")
    args = parser.parse_args()

    d = args.dir
    rtt_results  = load_json_files(os.path.join(d, "rtt_results_*.json"))
    conv_results = load_json_files(os.path.join(d, "convergence_*.json"))
    thru_results = load_json_files(os.path.join(d, "throughput_*.json"))

    print("\n" + "=" * 70)
    print("  RA-TDMAs+ — Test Results Summary")
    print("=" * 70)

    table_rtt(rtt_results)
    table_convergence(conv_results)
    table_throughput(thru_results)

    print()

if __name__ == "__main__":
    main()
