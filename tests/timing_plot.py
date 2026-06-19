#!/usr/bin/env python3
"""
timing_plot.py — Gráfico do timing TDMA do vídeo (histograma bimodal de
inter-arrivals), a partir dos JSON do tdma_timing_test.py.

Mostra a distribuição bimodal característica:
  - pico em 0–10 ms  → rajada de pacotes dentro do slot do N1
  - pico em ~140–150 ms → silêncio de 1 frame entre rajadas
e compara DIRETO vs RELAY lado a lado (devem ser ~idênticos → o relay não
altera o padrão TDMA). Equivalente à Fig. 4.35 da Ana.

Uso:
  python3 timing_plot.py tdma_timing_direct_*.json tdma_timing_relay_*.json --out timing.png
  python3 timing_plot.py results_*/tdma_timing_*.json --out figs/timing.png
"""

import sys, os, json, glob, argparse, re
from collections import defaultdict
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

SLOT_MS  = 50.0
FRAME_MS = 150.0


def _bucket_lo(key):
    m = re.match(r'(\d+)-', key)
    return int(m.group(1)) if m else None


def load_hist(path):
    """Devolve (topologia, {lo_ms: count}) de um JSON do tdma_timing_test."""
    with open(path) as f:
        d = json.load(f)
    label = d.get("label", os.path.basename(path))
    topo = "relay" if "relay" in label else "direct"
    hist = {}
    for k, v in (d.get("histogram") or {}).items():
        lo = _bucket_lo(k)
        if lo is not None:
            hist[lo] = hist.get(lo, 0) + v
    return topo, hist, d


def main():
    ap = argparse.ArgumentParser(description="Gráfico do timing TDMA do vídeo")
    ap.add_argument("files", nargs="+", help="JSON(s) do tdma_timing_test (aceita globs)")
    ap.add_argument("--out", default="timing_tdma.png", help="ficheiro PNG de saída")
    ap.add_argument("--bucket", type=float, default=10.0, help="largura do bucket (ms)")
    args = ap.parse_args()

    paths = []
    for f in args.files:
        paths.extend(sorted(glob.glob(f)) or ([f] if os.path.exists(f) else []))
    if not paths:
        print("ERRO: nenhum ficheiro encontrado.")
        print("  Dica: python3 timing_plot.py results_*/tdma_timing_*.json --out timing.png")
        sys.exit(1)

    # agrega histogramas por topologia
    agg = {"direct": defaultdict(int), "relay": defaultdict(int)}
    meta = {"direct": [], "relay": []}
    for p in paths:
        topo, hist, d = load_hist(p)
        for lo, c in hist.items():
            agg[topo][lo] += c
        if d.get("avg_ia_ms") is not None:
            meta[topo].append(d)

    topos = [t for t in ("direct", "relay") if agg[t]]
    n = len(topos)
    fig, axes = plt.subplots(1, n, figsize=(7 * n, 4.5), squeeze=False)

    titles = {"direct": "Direct (N1→N3)", "relay": "Relay (N1→N2→N3)"}
    colors = {"direct": "#2196F3", "relay": "#2E7D32"}

    for ax, topo in zip(axes[0], topos):
        los   = sorted(agg[topo])
        counts = [agg[topo][lo] for lo in los]
        ax.bar(los, counts, width=args.bucket * 0.9, align="edge",
               color=colors[topo], alpha=0.85, edgecolor="none")
        # marcas de slot e frame
        for x, lab in [(SLOT_MS, "slot 50ms"), (FRAME_MS, "frame 150ms")]:
            ax.axvline(x, color="gray", ls="--", lw=1, alpha=0.7)
            ax.text(x, ax.get_ylim()[1] * 0.95, lab, rotation=90,
                    va="top", ha="right", fontsize=8, color="gray")
        # média (se houver)
        if meta[topo]:
            avg_ia = np.mean([m["avg_ia_ms"] for m in meta[topo]])
            ax.text(0.97, 0.85, f"avg IA = {avg_ia:.1f} ms\n"
                                f"runs = {len(meta[topo])}",
                    transform=ax.transAxes, ha="right", fontsize=9,
                    bbox=dict(boxstyle="round", facecolor="white", alpha=0.85))
        ax.set_xlim(0, max(FRAME_MS * 1.3, max(los) + args.bucket))
        ax.set_xlabel("Inter-arrival (ms)")
        ax.set_ylabel("Number of packets")
        ax.set_title(titles[topo], fontsize=12, fontweight="bold")
        ax.grid(axis="y", alpha=0.3)

    fig.suptitle("Video TDMA timing — bimodal inter-arrival distribution\n"
                 "burst within the slot (0–10 ms) + one-frame gap (~140–150 ms)",
                 fontsize=12, fontweight="bold")
    plt.tight_layout()
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    plt.savefig(args.out, dpi=150)
    plt.close()
    print(f"[PLOT] {args.out}")
    for topo in topos:
        total = sum(agg[topo].values())
        burst = sum(c for lo, c in agg[topo].items() if lo < 10)
        print(f"  {topo:>7}: {total} inter-arrivals · {100*burst/total:.0f}% na rajada (<10ms)")


if __name__ == "__main__":
    main()
