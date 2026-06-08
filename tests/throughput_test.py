#!/usr/bin/env python3
"""
throughput_test.py — UDP throughput measurement over the mesh TUN network

Measures achievable UDP throughput for different packet sizes, comparing
direct (N3↔N1) vs relay (N3↔N2↔N1) topologies.

O servidor devolve estatísticas ao cliente no fim — o JSON final
inclui pkts recebidos, throughput real e PDR.

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

THRU_PORT    = 19877
REPORT_PORT  = 19878   # servidor envia resultado aqui para o cliente
HDR_SIZE     = 12      # seq(4) + timestamp(8)
DEFAULT_RATE = 4000    # kbps — conservador para WiFi ad-hoc TDMA

# ── servidor ──────────────────────────────────────────────────────────────────

def server_mode(bind_ip="0.0.0.0"):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((bind_ip, THRU_PORT))
    sock.settimeout(4.0)
    print(f"[THRU-SERVER] A escutar em {bind_ip}:{THRU_PORT}")

    report_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    while True:
        rx_count = 0
        rx_bytes = 0
        t_start  = None
        t_end    = None
        client_addr = None

        try:
            while True:
                data, addr = sock.recvfrom(65535)
                if client_addr is None:
                    client_addr = addr
                if len(data) < HDR_SIZE:
                    continue
                seq, = struct.unpack_from(">I", data, 0)
                if seq == 0xFFFFFFFF:
                    t_end = time.perf_counter()
                    break
                if t_start is None:
                    t_start = time.perf_counter()
                rx_count += 1
                rx_bytes += len(data)
        except socket.timeout:
            t_end = time.perf_counter()

        if t_start and t_end and t_end > t_start and client_addr:
            elapsed         = t_end - t_start
            throughput_kbps = (rx_bytes * 8) / elapsed / 1000
            print(f"[THRU-SERVER] Recebidos {rx_count} pkts / {rx_bytes}B "
                  f"em {elapsed:.2f}s = {throughput_kbps:.1f} kbps")

            # envia resultado de volta ao cliente
            report = json.dumps({
                "rx_count":       rx_count,
                "rx_bytes":       rx_bytes,
                "elapsed_s":      round(elapsed, 3),
                "throughput_kbps": round(throughput_kbps, 1),
            }).encode()
            try:
                report_sock.sendto(report, (client_addr[0], REPORT_PORT))
            except Exception:
                pass
        else:
            print("[THRU-SERVER] Sem dados ou erro de timing")

# ── cliente ───────────────────────────────────────────────────────────────────

def client_mode(target, duration, pkt_size, label, topology, rate_kbps=0):
    payload_size = max(HDR_SIZE, pkt_size)
    data_filler  = b"X" * (payload_size - HDR_SIZE)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # socket para receber relatório do servidor
    report_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    report_sock.bind(("0.0.0.0", REPORT_PORT))
    report_sock.settimeout(5.0)

    sent       = 0
    sent_bytes = 0
    seq        = 0

    target_kbps = rate_kbps if rate_kbps > 0 else DEFAULT_RATE
    pkt_bits    = payload_size * 8
    interval_s  = pkt_bits / (target_kbps * 1000)

    print(f"[THRU-CLIENT] Target={target}  PktSize={pkt_size}B  "
          f"Duration={duration}s  Rate≈{target_kbps}kbps  Label={label}")

    t_start = time.perf_counter()
    t_end   = t_start + duration
    t_next  = t_start

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

    # sentinel (3× para garantir chegada)
    sentinel = struct.pack(">I", 0xFFFFFFFF) + b"\x00" * (HDR_SIZE - 4 + len(data_filler))
    for _ in range(3):
        sock.sendto(sentinel, (target, THRU_PORT))

    elapsed_client  = time.perf_counter() - t_start
    sent_kbps       = (sent_bytes * 8) / elapsed_client / 1000

    sock.close()

    print(f"[THRU-CLIENT] Enviados {sent} pkts / {sent_bytes}B "
          f"em {elapsed_client:.2f}s = {sent_kbps:.1f} kbps")

    # aguarda relatório do servidor
    rx_count = rx_bytes = 0
    rx_kbps  = 0.0
    try:
        data, _ = report_sock.recvfrom(4096)
        rep = json.loads(data.decode())
        rx_count = rep["rx_count"]
        rx_bytes = rep["rx_bytes"]
        rx_kbps  = rep["throughput_kbps"]
        print(f"[THRU-CLIENT] Servidor recebeu {rx_count}/{sent} pkts "
              f"= {rx_kbps:.1f} kbps  PDR={rx_count/sent*100:.1f}%")
    except socket.timeout:
        print("[THRU-CLIENT] Sem resposta do servidor (timeout)")
    except Exception as e:
        print(f"[THRU-CLIENT] Erro no relatório: {e}")

    report_sock.close()

    pdr = rx_count / sent * 100 if sent > 0 else 0.0

    result = {
        "label":              label,
        "topology":           topology,
        "target":             target,
        "pkt_size_bytes":     pkt_size,
        "rate_target_kbps":   target_kbps,
        "duration_s":         round(elapsed_client, 3),
        "pkts_sent":          sent,
        "bytes_sent":         sent_bytes,
        "throughput_sent_kbps": round(sent_kbps, 1),
        "pkts_received":      rx_count,
        "bytes_received":     rx_bytes,
        "throughput_kbps":    round(rx_kbps, 1),
        "pdr_pct":            round(pdr, 1),
        "timestamp":          time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    fname = f"throughput_{label}.json"
    with open(fname, "w") as f:
        json.dump(result, f, indent=2)
    print(f"[THRU-CLIENT] Guardado → {fname}")

# ── main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode",     choices=["client","server"], required=True)
    parser.add_argument("--target",   default="10.0.0.1")
    parser.add_argument("--duration", type=int,   default=10)
    parser.add_argument("--pktsize",  type=int,   default=1316,
                        help="Tamanho do payload UDP em bytes (1316=mpegts)")
    parser.add_argument("--label",    default="test")
    parser.add_argument("--topology", default="direct",
                        choices=["direct","relay","3hop"])
    parser.add_argument("--rate",     type=int, default=0,
                        help=f"Taxa em kbps (0=auto {DEFAULT_RATE}kbps)")
    args = parser.parse_args()

    if args.mode == "server":
        server_mode()
    else:
        client_mode(args.target, args.duration, args.pktsize,
                    args.label, args.topology, args.rate)
