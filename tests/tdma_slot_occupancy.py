#!/usr/bin/env python3
"""
tdma_slot_occupancy.py — Ocupação de slots TDMA por nó (estilo Fig. 4.34 da Ana)

Prova que os TRÊS nós respeitam os seus slots TDMA, usando os beacons de
sincronização (1 por nó por frame). Cada nó é identificado pelo IP físico de
origem (172.20.10.1/2/3) e a sua posição é "wrapped" ao frame de 150 ms.

Ao contrário do vídeo (que só o N1 gera e por isso só prova o slot do N1), os
beacons são enviados pelos três nós — logo mostram os três a ocupar zonas de
slot distintas e sem sobreposição.

Uso:
  python3 tdma_slot_occupancy.py captura.csv
  python3 tdma_slot_occupancy.py direto.csv relayn3.csv     # lado a lado

O CSV é o mesmo export do Wireshark usado no tdma_relay_analysis.py.
"""

import sys
import os
import argparse
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from collections import defaultdict

# reutiliza o parsing e o alinhamento do tdma_relay_analysis
from tdma_relay_analysis import (
    load_csv, FRAME_MS, SLOT_MS, _align_offset, _circular_mean,
)

NODE_COLOR = {1: '#2196F3', 2: '#4CAF50', 3: '#F44336'}
SLOTS = [(1, 0, 50), (2, 50, 100), (3, 100, 150)]   # (nó, início, fim) em ms


def beacon_positions(rows, offset):
    """
    Posições (mod 150ms, já alinhadas) dos beacons de cada nó físico.
    Beacon = pacote RX (protocolo TDMA custom) vindo de 172.20.10.{1,2,3}.
    Devolve dict {node: np.array(posicoes)}.
    """
    by_node = defaultdict(list)
    for r in rows:
        if r['proto'] != 'RX':
            continue
        node = {'172.20.10.1': 1, '172.20.10.2': 2, '172.20.10.3': 3}.get(r['src'])
        if node is None:
            continue
        by_node[node].append((r['ts_ms'] + offset) % FRAME_MS)
    return {n: np.array(v) for n, v in by_node.items()}


def print_stats(by_node, label):
    """Imprime, por nó, quantos beacons caíram dentro do slot esperado."""
    print(f"\n─── {label}: ocupação de slots (beacons por nó) ──────────────────────")
    print(f"  {'Nó':>4}  {'Slot':>12}  {'beacons':>8}  {'média (ms)':>11}  {'% no slot':>10}")
    for node, s_lo, s_hi in [(n, lo, hi) for n, lo, hi in SLOTS]:
        pos = by_node.get(node, np.array([]))
        if len(pos) == 0:
            print(f"  N{node:>2}   {s_lo:.0f}–{s_hi:.0f} ms      (sem beacons)")
            continue
        inside = np.sum((pos >= s_lo) & (pos < s_hi))
        pct = 100.0 * inside / len(pos)
        print(f"  N{node:>2}   {s_lo:>4.0f}–{s_hi:<4.0f} ms  {len(pos):>8}  "
              f"{_circular_mean(pos):>11.1f}  {pct:>9.1f}%")


def plot_occupancy(captures, out_path):
    """
    captures: lista de (label, by_node). Faz um scatter por captura (estilo
    Fig. 4.34): eixo Y = nó emissor, eixo X = posição no frame, zonas de slot
    sombreadas. Cada nó deve cair na sua zona → prova de respeito dos slots.
    """
    n = len(captures)
    fig, axes = plt.subplots(1, n, figsize=(7.5 * n, 4.5), squeeze=False)

    for ax, (label, by_node) in zip(axes[0], captures):
        # zonas de slot
        for node, s_lo, s_hi in SLOTS:
            ax.axvspan(s_lo, s_hi, alpha=0.07, color=NODE_COLOR[node])
            ax.axvline(s_hi, color='gray', ls='--', lw=1, alpha=0.6)
        # pontos por nó (usa os últimos 400 para não saturar)
        for node in (1, 2, 3):
            pos = by_node.get(node, np.array([]))[-400:]
            if len(pos) == 0:
                continue
            ax.scatter(pos, np.full(len(pos), node), s=6, alpha=0.5,
                       color=NODE_COLOR[node], label=f'N{node}')
        ax.set_xlim(0, FRAME_MS)
        ax.set_ylim(0.5, 3.5)
        ax.set_yticks([1, 2, 3])
        ax.set_yticklabels(['N1', 'N2', 'N3'])
        ax.set_xlabel('Position within TDMA frame (ms)', fontsize=11)
        ax.set_ylabel('Transmitting node', fontsize=11)
        ax.set_title(label, fontsize=12, fontweight='bold')
        ax.grid(axis='x', alpha=0.2)
        # rótulos das zonas
        for node, s_lo, s_hi in SLOTS:
            ax.text((s_lo + s_hi) / 2, 3.4, f'N{node} slot', ha='center', va='top',
                    fontsize=9, color=NODE_COLOR[node])

    fig.suptitle('TDMA Slot Occupancy by Node (beacons) — each node stays in its slot',
                 fontsize=13, fontweight='bold')
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"\n[PLOT] {out_path}")


def main():
    ap = argparse.ArgumentParser(description='Ocupação de slots TDMA por nó (beacons)')
    ap.add_argument('files', nargs='+', help='1 ou 2 CSVs Wireshark (captura em N3)')
    ap.add_argument('--out', default='slot_occupancy.png', help='ficheiro de saída PNG')
    args = ap.parse_args()

    captures = []
    for f in args.files:
        if not os.path.exists(f):
            print(f"ERRO: {f} não encontrado"); sys.exit(1)
        rows = load_csv(f)
        offset, note = _align_offset(rows)
        by_node = beacon_positions(rows, offset)
        label = os.path.splitext(os.path.basename(f))[0] + f'  ({note})'
        print_stats(by_node, label)
        captures.append((label, by_node))

    plot_occupancy(captures, args.out)


if __name__ == '__main__':
    main()
