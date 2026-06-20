#!/usr/bin/env python3
"""
throughput_test.py — Medição passiva de throughput do vídeo UDP

Mede o tráfego de vídeo que JÁ está a fluir de N1→N3 (porta 5000),
sem injectar tráfego extra. Observa o tráfego com um sniffer raw (AF_PACKET)
para NÃO ocupar a porta 5000 — assim co-existe com o ffplay/base_station.py sem
"Address already in use" e sem roubar pacotes ao vídeo. Sem root, cai para o
método antigo de SO_REUSEPORT (ver video_sniff.py).

Uso (apenas no Nó 3, enquanto base_station.py corre):
    sudo python3 throughput_test.py --duration 15 --label "direct_1"
    sudo python3 throughput_test.py --duration 15 --label "relay_1" --topology relay
    # --iface wlp5s0  para fixar a interface do sniffer (default: todas)
"""

import time
import json
import argparse
import statistics

from video_sniff import VideoTap, VideoTapError

VIDEO_PORT = 5000

def measure(duration, label, topology, iface=None):
    try:
        tap = VideoTap(VIDEO_PORT, iface=iface)
    except VideoTapError as e:
        print(f"[THRU] {e}")
        return

    print(f"[THRU] Medição passiva porta {VIDEO_PORT}  duração={duration}s  label={label}")
    print(f"[THRU] A aguardar tráfego de vídeo...")

    rx_pkts  = 0
    rx_bytes = 0
    t_start  = None
    pkt_sizes = []
    arr_t     = []   # tempos de chegada (s) relativos ao 1º pacote — p/ série temporal

    deadline = time.perf_counter() + duration + 3.0  # 3s extra para arranque

    while time.perf_counter() < deadline:
        r = tap.recv()
        if r is None:                       # timeout do socket
            if t_start and time.perf_counter() > t_start + duration:
                break
            continue
        if r is False:                      # trama capturada mas não é vídeo
            continue
        now, plen = r

        if t_start is None:
            t_start  = now
            deadline = now + duration
            print(f"[THRU] Primeiro pacote recebido — a medir {duration}s...")

        rx_pkts  += 1
        rx_bytes += plen
        pkt_sizes.append(plen)
        arr_t.append(now - t_start)

        if rx_pkts % 500 == 0:
            elapsed = now - t_start
            kbps    = (rx_bytes * 8) / elapsed / 1000 if elapsed > 0 else 0
            print(f"\r[THRU] {rx_pkts} pkts  {kbps:.0f} kbps  {elapsed:.1f}s/{duration}s",
                  end="", flush=True)

    tap.close()
    print()

    if not t_start or rx_pkts == 0:
        print("[THRU] Sem dados — o vídeo está a chegar à porta 5000?")
        return

    elapsed      = min(time.perf_counter() - t_start, duration)
    throughput_kbps = (rx_bytes * 8) / elapsed / 1000
    avg_pkt      = statistics.mean(pkt_sizes) if pkt_sizes else 0
    pps          = rx_pkts / elapsed

    # série temporal de throughput (kbps por bin de 1s) — para o gráfico de onda.
    # usa os MESMOS pacotes/bytes da medição, por isso é a mesma medida veridica.
    BIN_S = 1.0
    nbins = max(1, int(elapsed / BIN_S) + 1)
    bin_bytes = [0] * nbins
    for t, b in zip(arr_t, pkt_sizes):
        idx = int(t / BIN_S)
        if 0 <= idx < nbins:
            bin_bytes[idx] += b
    series_kbps = [round(bb * 8 / BIN_S / 1000, 1) for bb in bin_bytes]

    print(f"\n{'='*50}")
    print(f"  Label:      {label}")
    print(f"  Topology:   {topology}")
    print(f"  Duração:    {elapsed:.2f}s")
    print(f"  Pacotes:    {rx_pkts}")
    print(f"  Bytes:      {rx_bytes/1024:.1f} KB")
    print(f"  Throughput: {throughput_kbps:.1f} kbps")
    print(f"  PPS:        {pps:.1f} pkt/s")
    print(f"  Pkt médio:  {avg_pkt:.0f} B")
    print(f"{'='*50}")

    result = {
        "label":           label,
        "topology":        topology,
        "direction":       "N1_to_N3",
        "duration_s":      round(elapsed, 3),
        "pkts_received":   rx_pkts,
        "bytes_received":  rx_bytes,
        "throughput_kbps": round(throughput_kbps, 1),
        "pps":             round(pps, 1),
        "pkt_size_bytes":  round(avg_pkt, 1),   # alias esperado por results_summary.py
        "avg_pkt_bytes":   round(avg_pkt, 1),
        "bin_s":           BIN_S,
        "series_kbps":     series_kbps,         # throughput por segundo → gráfico de onda
        "timestamp":       time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    fname = f"throughput_{label}.json"
    with open(fname, "w") as f:
        json.dump(result, f, indent=2)
    print(f"  Guardado → {fname}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=int,   default=15)
    parser.add_argument("--label",    default="test")
    parser.add_argument("--topology", default="direct", choices=["direct", "relay"])
    parser.add_argument("--iface",    default=None,
                        help="Interface do sniffer raw (default: todas)")
    args = parser.parse_args()

    measure(args.duration, args.label, args.topology, args.iface)
