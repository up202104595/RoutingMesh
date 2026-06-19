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
        print(f"  [{label}] sem amostras")
        return
    fast, slow, thr = split_clusters(samples, frame_ms)
    n = len(samples)
    print(f"\n─── {label} ───────────────────────────────")
    print(f"  n={n}  avg={samples.mean():.1f}  med={np.median(samples):.1f}  "
          f"min={samples.min():.1f}  max={samples.max():.1f}  "
          f"std={samples.std():.1f} ms")
    if len(fast) and len(slow):
        sep = slow.mean() - fast.mean()
        print(f"  Cluster RÁPIDO (apanha a ronda): {len(fast):>3} pings "
              f"({100*len(fast)/n:4.1f}%)  μ={fast.mean():.1f} ms")
        print(f"  Cluster LENTO  (falha 1 ronda):  {len(slow):>3} pings "
              f"({100*len(slow)/n:4.1f}%)  μ={slow.mean():.1f} ms")
        print(f"  Separação entre clusters: {sep:.1f} ms  "
              f"(≈ {sep/frame_ms:.2f} frame; esperado ≈ 1.0)")
    else:
        only = "RÁPIDO" if len(fast) else "LENTO"
        print(f"  Distribuição unimodal (só cluster {only})")


def plot_timeseries(ax, samples, frame_ms, title):
    x = np.arange(1, len(samples) + 1)
    fast, slow, thr = split_clusters(samples, frame_ms)
    ax.plot(x, samples, color='#90A4AE', lw=0.8, zorder=1)
    mask_fast = samples < thr
    ax.scatter(x[mask_fast],  samples[mask_fast],  s=16, color='#2196F3',
               label='apanha a ronda (~1 slot)', zorder=2)
    ax.scatter(x[~mask_fast], samples[~mask_fast], s=16, color='#F44336',
               label='falha 1 ronda (+1 frame)', zorder=2)
    if len(samples):
        ax.axhline(samples.min(), color='#2196F3', ls=':', lw=1, alpha=0.6)
        ax.axhline(samples.min() + frame_ms, color='#F44336', ls=':', lw=1,
                   alpha=0.6, label=f'piso + 1 frame ({frame_ms:.0f} ms)')
    ax.set_xlabel('Número de sequência do ping')
    ax.set_ylabel('RTT (ms)')
    ax.set_title(title, fontsize=11, fontweight='bold')
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc='upper right')


def plot_histogram(ax, samples, frame_ms, title):
    if len(samples) == 0:
        return
    bins = np.arange(0, samples.max() + 10, 5)
    ax.hist(samples, bins=bins, color='#5C6BC0', alpha=0.85, edgecolor='none')
    ax.axvline(np.median(samples), color='red', lw=1.6, ls='--',
               label=f'mediana {np.median(samples):.0f} ms')
    ax.axvline(samples.mean(), color='black', lw=1.6, ls=':',
               label=f'média {samples.mean():.0f} ms')
    ax.set_xlabel('RTT (ms)')
    ax.set_ylabel('Contagem')
    ax.set_title(title, fontsize=11, fontweight='bold')
    ax.grid(axis='y', alpha=0.3)
    ax.legend(fontsize=8)


def main():
    ap = argparse.ArgumentParser(description='Gráficos de RTT para a dissertação')
    ap.add_argument('files', nargs='+', help='JSON(s) do rtt_test (aceita globs)')
    ap.add_argument('--frame', type=float, default=FRAME_MS_DEFAULT,
                    help=f'duração do frame TDMA em ms (default {FRAME_MS_DEFAULT:.0f})')
    ap.add_argument('--out', default='.', help='pasta de saída dos PNG')
    args = ap.parse_args()

    # expande globs (útil quando a shell não o faz)
    paths = []
    for f in args.files:
        m = sorted(glob.glob(f))
        if m:
            paths.extend(m)
        elif os.path.exists(f):
            paths.append(f)
        else:
            print(f"[AVISO] nada corresponde a '{f}'")
    if not paths:
        print("ERRO: nenhum ficheiro encontrado.")
        print("  Dica: os JSON ficam em tests/results_*/  — ex.:")
        print("    python3 tests/rtt_plot.py tests/results_*/rtt_results_*.json --out figs_rtt")
        sys.exit(1)

    os.makedirs(args.out, exist_ok=True)
    all_samples = []

    for path in paths:
        if not os.path.exists(path):
            print(f"ERRO: não encontrado: {path}"); continue
        d, samples = load(path)
        if len(samples) == 0:
            print(f"[AVISO] {path}: sem campo 'samples' (regrava com rtt_test atualizado)")
            continue
        label = d.get('label', os.path.basename(path))
        print_summary(label, samples, args.frame)
        all_samples.append(samples)

        fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 4.5))
        plot_timeseries(a1, samples, args.frame, f'RTT por sequência — {label}')
        plot_histogram(a2, samples, args.frame, f'Distribuição RTT — {label}')
        fig.suptitle(f"RTT TDMA — {label}  "
                     f"(avg {samples.mean():.0f} ms, PDR {d.get('pdr_pct','?')}%)",
                     fontsize=12, fontweight='bold')
        plt.tight_layout()
        out = os.path.join(args.out, f"rtt_{label}.png")
        plt.savefig(out, dpi=150); plt.close()
        print(f"  [PLOT] {out}")

    # agregado de todas as runs
    if len(all_samples) > 1:
        agg = np.concatenate(all_samples)
        print_summary("AGREGADO (todas as runs)", agg, args.frame)
        fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 4.5))
        plot_timeseries(a1, agg, args.frame, 'RTT por sequência — agregado')
        plot_histogram(a2, agg, args.frame, 'Distribuição RTT — agregado')
        fig.suptitle(f"RTT TDMA — agregado de {len(all_samples)} runs "
                     f"(n={len(agg)}, avg {agg.mean():.0f} ms)",
                     fontsize=12, fontweight='bold')
        plt.tight_layout()
        out = os.path.join(args.out, "rtt_agregado.png")
        plt.savefig(out, dpi=150); plt.close()
        print(f"  [PLOT] {out}")


if __name__ == '__main__':
    main()
