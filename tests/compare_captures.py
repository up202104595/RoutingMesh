#!/usr/bin/env python3
"""
compare_captures.py — Compara duas (ou mais) capturas Wireshark lado a lado.

Mostra, por ficheiro: total de pacotes, quantos são beacons (RX ~107B),
vídeo (porta 5000 / MPEG TS), e a posição/% no slot de cada nó (pelos beacons).
Serve para perceber porque é que duas capturas "iguais" diferem.

Uso:
    python3 tests/compare_captures.py tdma_direto.csv direto2.csv
"""

import sys
import os
import numpy as np
from collections import Counter

from tdma_relay_analysis import (
    load_csv, FRAME_MS, SLOT_MS, _circular_mean, is_tdma_beacon, _n1_beacon_pos,
)

SLOT_START = {1: 0.0, 2: 50.0, 3: 100.0}


def summarize(path):
    rows = load_csv(path)
    n = len(rows)
    protos = Counter(r['proto'] for r in rows)
    beacons = [r for r in rows if is_tdma_beacon(r)]
    video = [r for r in rows if r['ptype'] == 'video_udp']

    # alinha N1 ao centro do slot (25ms)
    b = _n1_beacon_pos(rows)
    offset = (25.0 - b) if b is not None else 0.0

    print(f"\n══ {os.path.basename(path)} ══")
    print(f"  Total pacotes      : {n}")
    print(f"  Protocolos         : {dict(protos)}")
    print(f"  Beacons (RX 88-120B) : {len(beacons)}")
    print(f"  Vídeo (5000/MPEGTS): {len(video)}")
    print(f"  {'Nó':>3}  {'beacons':>8}  {'μ (ms)':>8}  {'σ (ms)':>8}  {'% no slot':>10}")
    for node in (1, 2, 3):
        ip = f'172.20.10.{node}'
        pos = np.array([(r['ts_ms'] + offset) % FRAME_MS
                        for r in beacons if r['src'] == ip])
        if len(pos) == 0:
            print(f"  N{node:>2}   {'(sem beacons)':>8}")
            continue
        s_lo = SLOT_START[node]; s_hi = s_lo + SLOT_MS
        pct = 100.0 * np.sum((pos >= s_lo) & (pos < s_hi)) / len(pos)
        print(f"  N{node:>2}  {len(pos):>8}  {_circular_mean(pos):>8.1f}  "
              f"{np.std(pos):>8.2f}  {pct:>9.1f}%")


def main():
    if len(sys.argv) < 2:
        print("Uso: python3 tests/compare_captures.py ficheiro1.csv [ficheiro2.csv ...]")
        sys.exit(1)
    for f in sys.argv[1:]:
        if not os.path.exists(f):
            print(f"ERRO: {f} não encontrado"); continue
        summarize(f)


if __name__ == '__main__':
    main()
