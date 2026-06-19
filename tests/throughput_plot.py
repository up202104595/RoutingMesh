#!/usr/bin/env python3
"""
throughput_plot.py — Video throughput bar chart (direct vs relay) for the thesis.

Reads the JSON produced by throughput_test.py (throughput_*.json), groups by
topology, and draws a bar chart of the mean throughput with error bars (std
across repetitions). Marks the encoder target as a reference line and annotates
the relay overhead.

Usage:
  python3 throughput_plot.py results_*/throughput_*.json --out figs/throughput.png
  python3 throughput_plot.py results_*/throughput_*.json --title "Video stream throughput" --out figs/throughput.png
"""

import sys, os, json, glob, argparse
from collections import defaultdict
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

LABELS = {'direct': 'Direct\n(N1→N3)', 'relay': 'Relay\n(N1→N2→N3)'}
COLORS = {'direct': '#2196F3', 'relay': '#2E7D32'}


def load(path):
    with open(path) as f:
        d = json.load(f)
    return d.get('topology', '?'), float(d.get('throughput_kbps', 0.0))


def main():
    ap = argparse.ArgumentParser(description='Video throughput bar chart (direct vs relay)')
    ap.add_argument('files', nargs='+', help='throughput_*.json (accepts globs)')
    ap.add_argument('--out', default='throughput.png', help='output PNG')
    ap.add_argument('--title', default='Video stream throughput', help='figure title')
    ap.add_argument('--target', type=float, default=500.0,
                    help='encoder target in kbps for the reference line (0 to disable)')
    args = ap.parse_args()

    paths = []
    for f in args.files:
        paths.extend(sorted(glob.glob(f)) or ([f] if os.path.exists(f) else []))
    if not paths:
        print('ERROR: no files found.')
        print('  Hint: python3 throughput_plot.py tests/results_*/throughput_*.json --out figs/throughput.png')
        sys.exit(1)

    by = defaultdict(list)
    for p in paths:
        topo, kbps = load(p)
        if kbps > 0:
            by[topo].append(kbps)

    order = [t for t in ('direct', 'relay') if t in by]
    if not order:
        print('ERROR: no throughput data parsed.'); sys.exit(1)

    means = [float(np.mean(by[t])) for t in order]
    stds  = [float(np.std(by[t]))  for t in order]
    x = np.arange(len(order))

    fig, ax = plt.subplots(figsize=(6, 5))
    bars = ax.bar(x, means, yerr=stds, capsize=6, width=0.55,
                  color=[COLORS.get(t, '#777') for t in order],
                  alpha=0.85, edgecolor='white')
    for b, m in zip(bars, means):
        ax.text(b.get_x() + b.get_width() / 2, m + max(means) * 0.015,
                f'{m:.0f} kbps', ha='center', fontsize=11, fontweight='bold')

    if args.target and args.target > 0:
        ax.axhline(args.target, color='gray', ls='--', lw=1)
        ax.text(len(order) - 0.45, args.target + max(means) * 0.01,
                f'encoder target {args.target:.0f} kbps',
                ha='right', va='bottom', fontsize=8, color='gray')

    ax.set_xticks(x)
    ax.set_xticklabels([LABELS.get(t, t) for t in order])
    ax.set_ylabel('Throughput (kbps)')
    ax.set_title(args.title, fontsize=12, fontweight='bold')
    ax.set_ylim(0, max(means) * 1.25)
    ax.grid(axis='y', alpha=0.3)

    if len(order) == 2 and means[0] > 0:
        ov = (means[0] - means[1]) / means[0] * 100
        ax.text(0.5, 0.02, f'relay overhead: {ov:+.1f}\\%',
                transform=ax.transAxes, ha='center', fontsize=9, style='italic')

    plt.tight_layout()
    os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)
    plt.savefig(args.out, dpi=150)
    plt.close()
    print(f'[PLOT] {args.out}')
    for t in order:
        print(f'  {t:>7}: mean {np.mean(by[t]):.1f} kbps  (n={len(by[t])})')


if __name__ == '__main__':
    main()
