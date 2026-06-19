#!/usr/bin/env python3
"""
tdma_timing_test.py — Análise de timing TDMA dos pacotes de vídeo

Observa passivamente o vídeo na porta 5000 (sniffer raw AF_PACKET, NÃO ocupa a
porta — co-existe com o ffplay sem "Address already in use") e regista o
timestamp exato de cada pacote. Analisa os inter-arrivals para verificar se os
pacotes chegam alinhados com as slots TDMA (frame=150ms, slot=50ms).
Sem root cai para SO_REUSEPORT (ver video_sniff.py).

Uso (no Nó 3, com vídeo a fluir):
    sudo python3 tests/tdma_timing_test.py --duration 30 --label "direct"
    sudo python3 tests/tdma_timing_test.py --duration 30 --label "relay"
    # --iface wlp5s0  para fixar a interface do sniffer (default: todas)
"""

import time
import json
import argparse
import statistics

from video_sniff import VideoTap

VIDEO_PORT   = 5000
TDMA_SLOT_MS = 50.0    # duração de cada slot
TDMA_FRAME_MS = 150.0  # duração da frame completa (3 nós)


def measure(duration, label, iface=None):
    tap = VideoTap(VIDEO_PORT, iface=iface)

    print(f"[TDMA] Label={label}  Duração={duration}s")
    print(f"[TDMA] A aguardar vídeo na porta {VIDEO_PORT}...")

    timestamps = []
    deadline = time.perf_counter() + duration + 3.0  # 3s extra para arranque
    t_start = None

    while time.perf_counter() < deadline:
        r = tap.recv()
        if r is None:                       # timeout do socket
            if t_start and time.perf_counter() > t_start + duration:
                break
            continue
        if r is False:                      # trama capturada mas não é vídeo
            continue
        now, _ = r
        if t_start is None:
            t_start = now
            deadline = now + duration
            print(f"[TDMA] Primeiro pacote — a medir {duration}s...")
        timestamps.append(now)
        if len(timestamps) % 200 == 0:
            elapsed = now - t_start
            print(f"\r[TDMA] {len(timestamps)} pkts  {elapsed:.1f}s/{duration}s",
                  end="", flush=True)

    tap.close()
    print()

    if len(timestamps) < 2:
        print("[TDMA] Pacotes insuficientes.")
        return

    # inter-arrivals em ms
    ias = [(timestamps[i] - timestamps[i-1]) * 1000
           for i in range(1, len(timestamps))]

    ias_sorted = sorted(ias)
    n = len(ias)

    def pct(p):
        idx = int(p / 100 * n)
        return ias_sorted[min(idx, n-1)]

    avg_ia  = statistics.mean(ias)
    med_ia  = statistics.median(ias)
    std_ia  = statistics.stdev(ias)
    min_ia  = min(ias)
    max_ia  = max(ias)
    p95     = pct(95)
    p99     = pct(99)

    # buckets alinhados ao TDMA
    bucket_w = 10.0  # ms por bucket
    max_bucket = int(min(max_ia, TDMA_FRAME_MS * 3) / bucket_w) + 1
    buckets = [0] * (max_bucket + 1)
    over = 0
    for ia in ias:
        idx = int(ia / bucket_w)
        if idx < len(buckets):
            buckets[idx] += 1
        else:
            over += 1

    # pico dominante
    peak_bucket = buckets.index(max(buckets))
    peak_ms = peak_bucket * bucket_w + bucket_w / 2

    # percentagem de pacotes dentro de ±20ms de cada múltiplo do slot
    def near_multiple(ia, mult, tol=20):
        return any(abs(ia - k * mult) < tol for k in range(1, 10))

    near_slot  = sum(1 for ia in ias if near_multiple(ia, TDMA_SLOT_MS))  / n * 100
    near_frame = sum(1 for ia in ias if near_multiple(ia, TDMA_FRAME_MS)) / n * 100

    print(f"\n{'='*56}")
    print(f"  Label:    {label}")
    print(f"  Pacotes:  {len(timestamps)}  |  Inter-arrivals: {n}")
    print(f"{'='*56}")
    print(f"  Avg IA:   {avg_ia:8.2f} ms")
    print(f"  Med IA:   {med_ia:8.2f} ms")
    print(f"  Std IA:   {std_ia:8.2f} ms")
    print(f"  Min IA:   {min_ia:8.2f} ms")
    print(f"  Max IA:   {max_ia:8.2f} ms")
    print(f"  P95 IA:   {p95:8.2f} ms")
    print(f"  P99 IA:   {p99:8.2f} ms")
    print(f"  Pico dom: {peak_ms:8.1f} ms  (bucket {peak_bucket}×{bucket_w}ms)")
    print(f"{'='*56}")
    print(f"  % perto de múltiplo de slot  ({TDMA_SLOT_MS}ms ±20ms): {near_slot:5.1f}%")
    print(f"  % perto de múltiplo de frame ({TDMA_FRAME_MS}ms ±20ms): {near_frame:5.1f}%")
    print(f"{'='*56}")

    # histograma ASCII (0–450ms)
    print(f"\n  Histograma inter-arrival (buckets de {bucket_w:.0f}ms):")
    print(f"  {'ms':>6}  {'count':>6}  {'bar'}")
    bar_max = max(buckets) if max(buckets) > 0 else 1
    for i, cnt in enumerate(buckets):
        lo = i * bucket_w
        hi = lo + bucket_w
        bar = '█' * int(cnt / bar_max * 40)
        # marca slots e frames TDMA
        mark = ""
        if abs(lo - TDMA_SLOT_MS) < bucket_w or abs(lo - TDMA_SLOT_MS*2) < bucket_w:
            mark = " ← slot"
        if abs(lo - TDMA_FRAME_MS) < bucket_w:
            mark = " ← FRAME"
        print(f"  {lo:5.0f}-{hi:<5.0f} {cnt:6d}  {bar}{mark}")
    if over:
        print(f"  >{(max_bucket)*bucket_w:.0f}ms        {over:6d}")

    result = {
        "label":          label,
        "timestamp":      time.strftime("%Y-%m-%dT%H:%M:%S"),
        "n_pkts":         len(timestamps),
        "n_ias":          n,
        "avg_ia_ms":      round(avg_ia,  2),
        "med_ia_ms":      round(med_ia,  2),
        "std_ia_ms":      round(std_ia,  2),
        "min_ia_ms":      round(min_ia,  2),
        "max_ia_ms":      round(max_ia,  2),
        "p95_ia_ms":      round(p95,     2),
        "p99_ia_ms":      round(p99,     2),
        "peak_ia_ms":     round(peak_ms, 1),
        "pct_near_slot_ms":  round(near_slot,  1),
        "pct_near_frame_ms": round(near_frame, 1),
        "tdma_slot_ms":   TDMA_SLOT_MS,
        "tdma_frame_ms":  TDMA_FRAME_MS,
        "histogram": {
            f"{int(i*bucket_w)}-{int((i+1)*bucket_w)}ms": cnt
            for i, cnt in enumerate(buckets)
        },
    }

    fname = f"tdma_timing_{label}.json"
    with open(fname, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\n  Guardado → {fname}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=int, default=30,
                        help="Duração da medição em segundos (default: 30)")
    parser.add_argument("--label", default="direct",
                        help="Etiqueta para o ficheiro JSON")
    parser.add_argument("--iface", default=None,
                        help="Interface do sniffer raw (default: todas)")
    args = parser.parse_args()
    measure(args.duration, args.label, args.iface)
