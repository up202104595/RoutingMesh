#!/usr/bin/env python3
"""
throughput_test.py — UDP throughput measurement over the mesh TUN network

Measures achievable UDP throughput for different packet sizes, comparing
direct (N3↔N1) vs relay (N3↔N2↔N1) topologies.

Usage:
  Server side (Node 1): python3 throughput_test.py --mode server
  Client side (Node 3): python3 throughput_test.py --mode client --target 10.0.0.1 \
                          --duration 10 --pktsize 1316 --label "direct_1316"

Packet size 1316 matches the video stream (mpegts UDP pkt_size=1316).
"""

import socket
import time
import json
import struct
import argparse
import threading
import statistics

THRU_PORT  = 19877
HDR_SIZE   = 12   # seq(4) + timestamp(8)

rx_count   = 0
rx_bytes   = 0
rx_lock    = threading.Lock()
rx_done    = False

def server_mode(bind_ip="0.0.0.0"):
    global rx_count, rx_bytes, rx_done

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((bind_ip, THRU_PORT))
    sock.settimeout(3.0)
    print(f"[THRU-SERVER] Listening on {bind_ip}:{THRU_PORT}")

    while True:
        rx_count = 0
        rx_bytes = 0
        rx_done  = False
        t_start  = None
        t_end    = None
        try:
            while True:
                data, addr = sock.recvfrom(65535)
                if len(data) < HDR_SIZE:
                    continue
                seq, = struct.unpack_from(">I", data, 0)
                if seq == 0xFFFFFFFF:
                    # end-of-stream sentinel
                    t_end = time.perf_counter()
                    break
                if t_start is None:
                    t_start = time.perf_counter()
                with rx_lock:
                    rx_count += 1
                    rx_bytes += len(data)
        except socket.timeout:
            t_end = time.perf_counter()

        if t_start and t_end and t_end > t_start:
            elapsed   = t_end - t_start
            throughput_kbps = (rx_bytes * 8) / elapsed / 1000
            pdr = rx_count  # no total known server-side, just report count
            print(f"[THRU-SERVER] Received {rx_count} pkts / {rx_bytes} bytes "
                  f"in {elapsed:.2f}s = {throughput_kbps:.1f} kbps")
        else:
            print("[THRU-SERVER] No data received or timing error")

def client_mode(target, duration, pkt_size, label, topology, rate_kbps=0):
    payload_size = max(HDR_SIZE, pkt_size)
    data_filler  = b"X" * (payload_size - HDR_SIZE)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    sent       = 0
    sent_bytes = 0
    seq        = 0

    # rate limiting: intervalo mínimo entre pacotes
    # se rate_kbps=0 usa ~10 Mbps (realista para mesh WiFi ad-hoc)
    target_kbps  = rate_kbps if rate_kbps > 0 else 10000
    pkt_bits     = payload_size * 8
    interval_s   = pkt_bits / (target_kbps * 1000)

    print(f"[THRU-CLIENT] Target={target}  PktSize={pkt_size}B  "
          f"Duration={duration}s  Rate≈{target_kbps}kbps  Label={label}")

    t_start  = time.perf_counter()
    t_end    = t_start + duration
    t_next   = t_start

    while time.perf_counter() < t_end:
        now = time.perf_counter()
        if now < t_next:
            time.sleep(t_next - now)
        seq   += 1
        ts     = time.perf_counter()
        pkt    = struct.pack(">Id", seq, ts) + data_filler
        t_next = ts + interval_s
        try:
            sock.sendto(pkt, (target, THRU_PORT))
            sent += 1
            sent_bytes += len(pkt)
        except Exception:
            pass

    # sentinel
    sentinel = struct.pack(">I", 0xFFFFFFFF) + b"\x00" * (HDR_SIZE - 4 + len(data_filler))
    for _ in range(3):
        sock.sendto(sentinel, (target, THRU_PORT))

    elapsed = time.perf_counter() - t_start
    throughput_kbps = (sent_bytes * 8) / elapsed / 1000

    sock.close()

    print(f"[THRU-CLIENT] Sent {sent} pkts / {sent_bytes} bytes "
          f"in {elapsed:.2f}s = {throughput_kbps:.1f} kbps")

    result = {
        "label":           label,
        "topology":        topology,
        "target":          target,
        "pkt_size_bytes":  pkt_size,
        "duration_s":      round(elapsed, 3),
        "pkts_sent":       sent,
        "bytes_sent":      sent_bytes,
        "throughput_kbps": round(throughput_kbps, 1),
        "timestamp":       time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    fname = f"throughput_{label}.json"
    with open(fname, "w") as f:
        json.dump(result, f, indent=2)
    print(f"[THRU-CLIENT] Saved → {fname}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode",     choices=["client","server"], required=True)
    parser.add_argument("--target",   default="10.0.0.1")
    parser.add_argument("--duration", type=int,   default=10)
    parser.add_argument("--pktsize",  type=int,   default=1316,
                        help="UDP payload size in bytes (1316=mpegts default)")
    parser.add_argument("--label",    default="test")
    parser.add_argument("--topology", default="direct",
                        choices=["direct","relay","3hop"])
    parser.add_argument("--rate",     type=int, default=0,
                        help="Taxa de envio em kbps (0=auto 10Mbps)")
    args = parser.parse_args()

    if args.mode == "server":
        server_mode()
    else:
        client_mode(args.target, args.duration, args.pktsize, args.label, args.topology, args.rate)
