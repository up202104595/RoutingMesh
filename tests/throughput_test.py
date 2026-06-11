#!/usr/bin/env python3
"""
throughput_test.py — Medição passiva de throughput do vídeo UDP

Mede o tráfego de vídeo que JÁ está a fluir de N1→N3 (porta 5000),
sem injectar tráfego extra. Usa SO_REUSEPORT para co-existir com
o base_station.py que também escuta na porta 5000.

Uso (apenas no Nó 3, enquanto base_station.py corre):
    python3 throughput_test.py --duration 15 --label "direct_1"
    python3 throughput_test.py --duration 15 --label "relay_1" --topology relay
"""

import socket
import time
import json
import struct
import argparse
import statistics

VIDEO_PORT = 5000

def measure(duration, label, topology, bind_ip="0.0.0.0"):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except AttributeError:
        pass
    sock.bind((bind_ip, VIDEO_PORT))
    sock.settimeout(0.1)

    print(f"[THRU] Medição passiva porta {VIDEO_PORT}  duração={duration}s  label={label}")
    print(f"[THRU] A aguardar tráfego de vídeo...")

    rx_pkts  = 0
    rx_bytes = 0
    t_start  = None
    pkt_sizes = []

    deadline = time.perf_counter() + duration + 3.0  # 3s extra para arranque

    while time.perf_counter() < deadline:
        try:
            data, _ = sock.recvfrom(65536)
            now = time.perf_counter()

            if t_start is None:
                t_start  = now
                deadline = now + duration
                print(f"[THRU] Primeiro pacote recebido — a medir {duration}s...")

            rx_pkts  += 1
            rx_bytes += len(data)
            pkt_sizes.append(len(data))

            if rx_pkts % 500 == 0:
                elapsed = now - t_start
                kbps    = (rx_bytes * 8) / elapsed / 1000 if elapsed > 0 else 0
                print(f"\r[THRU] {rx_pkts} pkts  {kbps:.0f} kbps  {elapsed:.1f}s/{duration}s",
                      end="", flush=True)

        except socket.timeout:
            if t_start and time.perf_counter() > t_start + duration:
                break

    sock.close()
    print()

    if not t_start or rx_pkts == 0:
        print("[THRU] Sem dados — o vídeo está a chegar à porta 5000?")
        return

    elapsed      = min(time.perf_counter() - t_start, duration)
    throughput_kbps = (rx_bytes * 8) / elapsed / 1000
    avg_pkt      = statistics.mean(pkt_sizes) if pkt_sizes else 0
    pps          = rx_pkts / elapsed

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
        "avg_pkt_bytes":   round(avg_pkt, 1),
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
    parser.add_argument("--bind",     default="0.0.0.0")
    args = parser.parse_args()

    measure(args.duration, args.label, args.topology, args.bind)
