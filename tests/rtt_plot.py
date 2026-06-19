#!/usr/bin/env python3
"""
rtt_plot.py — Gráficos de RTT para a dissertação (estilo Fig. 4.21/4.28 da Ana)

Lê os JSON produzidos pelo rtt_test.py (rtt_results_*.json) e gera, por cada
ficheiro e em agregado:

  1) RTT vs número de sequência (série temporal) — mostra os blocos/plateaus
     do regime "apanha o slot" (~50 ms) vs "falha por uma ronda" (~200 ms).
     Análogo às Fig. 4.28/4.29/4.30 da Ana.

  2) Histograma do RTT — mostra a distribuição bimodal (dois clusters separados
     por exatamente 1 frame). Análogo às Fig. 4.21/4.24 da Ana.

Também imprime um resumo bimodal: % de pings em cada cluster, média de cada um,
e a separação entre clusters (que deve ≈ 1 frame TDMA).

Uso:
  python3 rtt_plot.py rtt_results_direct_rtt_r1.json
  python3 rtt_plot.py results_quick_*/rtt_results_*.json            # vários
  python3 rtt_plot.py --frame 150 --out figs/ rtt_results_*.json
"""

import sys
import os
import re
import json
import argparse
import glob
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

FRAME_MS_DEFAULT = 150.0   # frame TDMA (3 nós × 50 ms)


def load(path):
    with open(path) as f:
        d = json.load(f)
    samples = d.get("samples") or []
    return d, np.array(samples, dtype=float)


def split_clusters(samples, frame_ms):
    """
    Divide as amostras em dois clusters: 'rápido' (apanhou a ronda) e 'lento'
    (falhou por ~1 frame). O limiar é colocado a meio do vão entre o mínimo e
    o mínimo+frame, robusto à dispersão dentro de cada cluster.
    """
    if len(samples) == 0:
        return samples, samples, frame_ms
    lo = samples.min()
    threshold = lo + frame_ms * 0.5      # meio do vão de 1 frame acima do piso
    fast = samples[samples < threshold]
    slow = samples[samples >= threshold]
    return fast, slow, threshold


def print_summary(label, samples, frame_ms):
    if len(samples) == 0:
        print(f"  [{label}] no samples")
        return
    fast, slow, thr = split_clusters(samples, frame_ms)
    n = len(samples)
    print(f"\n--- {label} ---")
    print(f"  n={n}  min={samples.min():.1f}  max={samples.max():.1f} ms")
    if len(fast) and len(slow):
        sep = slow.mean() - fast.mean()
        print(f"  catches round (~1 slot): {len(fast):>3} ({100*len(fast)/n:4.1f}%)  "
              f"center={fast.mean():.1f} ms")
        print(f"  misses 1 round (+1 frame): {len(slow):>3} ({100*len(slow)/n:4.1f}%)  "
              f"center={slow.mean():.1f} ms")
        print(f"  cluster gap: {sep:.1f} ms  (~{sep/frame_ms:.2f} frame; expected 1.0)")
    else:
        only = "fast" if len(fast) else "slow"
        print(f"  unimodal ({only} cluster only)")


def plot_timeseries(ax, samples, frame_ms, title):
    x = np.arange(1, len(samples) + 1)
    fast, slow, thr = split_clusters(samples, frame_ms)
    ax.plot(x, samples, color='#90A4AE', lw=0.8, zorder=1)
    mask_fast = samples < thr
    ax.scatter(x[mask_fast],  samples[mask_fast],  s=16, color='#2196F3',
               label='catches the round (~1 slot)', zorder=2)
    ax.scatter(x[~mask_fast], samples[~mask_fast], s=16, color='#F44336',
               label='misses 1 round (+1 frame)', zorder=2)
    if len(samples):
        ax.axhline(samples.min(), color='#2196F3', ls=':', lw=1, alpha=0.6)
        ax.axhline(samples.min() + frame_ms, color='#F44336', ls=':', lw=1,
                   alpha=0.6, label=f'floor + 1 frame ({frame_ms:.0f} ms)')
    ax.set_xlabel('Ping sequence number')
    ax.set_ylabel('RTT (ms)')
    ax.set_title(title, fontsize=11, fontweight='bold')
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc='upper right')


def plot_histogram(ax, samples, frame_ms, title):
    if len(samples) == 0:
        return
    bins = np.arange(0, samples.max() + 10, 5)
    ax.hist(samples, bins=bins, color='#5C6BC0', alpha=0.85, edgecolor='none')
    fast, slow, thr = split_clusters(samples, frame_ms)
    n = len(samples)
    # mostra os DOIS clusters (centro + %), não média/mediana (não relevantes p/ bimodal)
    if len(fast):
        ax.axvline(fast.mean(), color='#2196F3', lw=1.8,
                   label=f'catches round: {100*len(fast)/n:.0f}% @ {fast.mean():.0f} ms')
    if len(slow):
        ax.axvline(slow.mean(), color='#F44336', lw=1.8,
                   label=f'misses 1 round: {100*len(slow)/n:.0f}% @ {slow.mean():.0f} ms')
    ax.set_xlabel('RTT (ms)')
    ax.set_ylabel('Count')
    ax.set_title(title, fontsize=11, fontweight='bold')
    ax.grid(axis='y', alpha=0.3)
    ax.legend(fontsize=8)


def main():
    ap = argparse.ArgumentParser(description='Gráficos de RTT para a dissertação')
    ap.add_argument('files', nargs='+', help='JSON(s) do rtt_test (aceita globs)')
    ap.add_argument('--frame', type=float, default=FRAME_MS_DEFAULT,
                    help=f'duração do frame TDMA em ms (default {FRAME_MS_DEFAULT:.0f})')
    ap.add_argument('--out', default='.', help='pasta de saída dos PNG')
    ap.add_argument('--title', default=None,
                    help='título da figura (ex.: "RTT over the direct link"); '
                         'substitui a etiqueta r1/r2 e dá nome ao ficheiro')
    args = ap.parse_args()

    def _fname(s):
        return re.sub(r'[^A-Za-z0-9._-]+', '_', s).strip('_')

    # expande globs (útil quando a shell não o faz)
    paths = []
    for f in args.files:
        m = sorted(glob.glob(f))
        if m:
            paths.extend(m)
        elif os.path.exists(f):
            paths.append(f)
        else:
            print(f"[WARN] no match for '{f}'")
    if not paths:
        print("ERROR: no files found.")
        print("  Hint: JSONs live in tests/results_*/  — e.g.:")
        print("    python3 tests/rtt_plot.py tests/results_*/rtt_results_*.json --out figs_rtt")
        sys.exit(1)

    os.makedirs(args.out, exist_ok=True)
    all_samples = []

    for path in paths:
        if not os.path.exists(path):
            print(f"ERROR: not found: {path}"); continue
        d, samples = load(path)
        if len(samples) == 0:
            print(f"[WARN] {path}: no 'samples' field (re-run with updated rtt_test)")
            continue
        label = d.get('label', os.path.basename(path))
        print_summary(label, samples, args.frame)
        all_samples.append(samples)

        display = args.title or f"TDMA RTT — {label}"
        fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 4.5))
        plot_timeseries(a1, samples, args.frame, 'RTT per sequence')
        plot_histogram(a2, samples, args.frame, 'RTT distribution')
        fig.suptitle(display, fontsize=13, fontweight='bold')
        plt.tight_layout()
        out = os.path.join(args.out, f"{_fname(args.title) if args.title else 'rtt_'+label}.png")
        plt.savefig(out, dpi=150); plt.close()
        print(f"  [PLOT] {out}")

    # agregado de todas as runs
    if len(all_samples) > 1:
        agg = np.concatenate(all_samples)
        print_summary("AGGREGATE (all runs)", agg, args.frame)
        agg_title = args.title or f"TDMA RTT — aggregate of {len(all_samples)} runs"
        fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 4.5))
        plot_timeseries(a1, agg, args.frame, 'RTT per sequence')
        plot_histogram(a2, agg, args.frame, 'RTT distribution')
        fig.suptitle(agg_title, fontsize=13, fontweight='bold')
        plt.tight_layout()
        out = os.path.join(args.out, f"{_fname(args.title) if args.title else 'rtt_aggregate'}.png")
        plt.savefig(out, dpi=150); plt.close()
        print(f"  [PLOT] {out}")


if __name__ == '__main__':
    main()
