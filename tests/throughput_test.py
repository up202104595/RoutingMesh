#!/usr/bin/env python3
"""
throughput_test.py — Medição de throughput UDP na rede mesh TUN

Sentido real: Nó 1 (robot) envia → Nó 3 (PC) recebe.

  Nó 3 (servidor/receptor):
    python3 throughput_test.py --mode server --label "direct_1316"

  Nó 1 (cliente/emissor):
    python3 throughput_test.py --mode client --target 10.0.0.3 \
        --duration 15 --pktsize 1316

O servidor conta os pacotes recebidos, calcula throughput real e PDR,
e guarda o JSON no Nó 3 (onde correm as métricas).
O cliente imprime apenas estatísticas de envio.
"""

import socket
import time
import json
import struct
import argparse

THRU_PORT    = 19877
HDR_SIZE     = 12       # seq(4) + timestamp_send(8)
DEFAULT_RATE = 4000     # kbps — conservador para WiFi ad-hoc TDMA

# ── servidor (Nó 3) ───────────────────────────────────────────────────────────

def server_mode(bind_ip, label, topology):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((bind_ip, THRU_PORT))
    sock.settimeout(5.0)

    print(f"[THRU-SERVER] A escutar em {bind_ip}:{THRU_PORT}  label={label}")
    print(f"[THRU-SERVER] Aguarda que o Nó 1 inicie o envio...")

    rx_count   = 0
    rx_bytes   = 0
    t_start    = None
    t_end      = None
    last_seq   = -1
    out_of_order = 0
    pkt_size   = 0

    try:
        while True:
            data, addr = sock.recvfrom(65535)
            if len(data) < HDR_SIZE:
                continue

            seq, = struct.unpack_from(">I", data, 0)

            if seq == 0xFFFFFFFF:
                t_end = time.perf_counter()
                print(f"\n[THRU-SERVER] Sentinel recebido de {addr[0]} — a calcular...")
                break

            if t_start is None:
                t_start  = time.perf_counter()
                pkt_size = len(data)
                print(f"[THRU-SERVER] Primeiro pacote de {addr[0]}  seq={seq}  pktsize={pkt_size}B")

            if seq <= last_seq:
                out_of_order += 1
            last_seq = seq

            rx_count += 1
            rx_bytes += len(data)

            if rx_count % 500 == 0:
                print(f"\r[THRU-SERVER] Recebidos {rx_count} pkts...", end="", flush=True)

    except socket.timeout:
        t_end = time.perf_counter()
        print(f"\n[THRU-SERVER] Timeout — assumindo fim do teste")

    print()

    if not t_start or not t_end or t_end <= t_start:
        print("[THRU-SERVER] Sem dados suficientes para calcular")
        return

    elapsed         = t_end - t_start
    throughput_kbps = (rx_bytes * 8) / elapsed / 1000

    print(f"[THRU-SERVER] Recebidos : {rx_count} pkts / {rx_bytes/1024:.1f} KB")
    print(f"[THRU-SERVER] Duração   : {elapsed:.2f}s")
    print(f"[THRU-SERVER] Throughput: {throughput_kbps:.1f} kbps")
    print(f"[THRU-SERVER] Fora ordem: {out_of_order}")

    # PDR só calculável se o cliente enviou o total no sentinel
    # (guardamos rx_count; o run_all.sh pode correlacionar depois)
    result = {
        "label":              label,
        "topology":           topology,
        "direction":          "N1_to_N3",
        "pkt_size_bytes":     pkt_size,
        "elapsed_s":          round(elapsed, 3),
        "pkts_received":      rx_count,
        "bytes_received":     rx_bytes,
        "throughput_kbps":    round(throughput_kbps, 1),
        "out_of_order":       out_of_order,
        "timestamp":          time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    fname = f"throughput_{label}.json"
    with open(fname, "w") as f:
        json.dump(result, f, indent=2)
    print(f"[THRU-SERVER] Guardado → {fname}")
    sock.close()

# ── cliente (Nó 1) ────────────────────────────────────────────────────────────

def client_mode(target, duration, pkt_size, rate_kbps):
    payload_size = max(HDR_SIZE, pkt_size)
    data_filler  = b"X" * (payload_size - HDR_SIZE)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    target_kbps = rate_kbps if rate_kbps > 0 else DEFAULT_RATE
    interval_s  = (payload_size * 8) / (target_kbps * 1000)

    print(f"[THRU-CLIENT] Target={target}:{THRU_PORT}  PktSize={pkt_size}B  "
          f"Duration={duration}s  Rate≈{target_kbps}kbps")

    sent       = 0
    sent_bytes = 0
    seq        = 0
    t_start    = time.perf_counter()
    t_end      = t_start + duration
    t_next     = t_start

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

    # sentinel com total enviado
    sentinel = struct.pack(">II", 0xFFFFFFFF, sent) + b"\x00" * (payload_size - 8)
    for _ in range(5):
        try:
            sock.sendto(sentinel, (target, THRU_PORT))
        except Exception:
            pass
        time.sleep(0.05)

    elapsed = time.perf_counter() - t_start
    print(f"[THRU-CLIENT] Enviados {sent} pkts / {sent_bytes/1024:.1f} KB "
          f"em {elapsed:.2f}s = {(sent_bytes*8)/elapsed/1000:.1f} kbps")
    sock.close()

# ── main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode",     choices=["client","server"], required=True)
    parser.add_argument("--target",   default="10.0.0.3",
                        help="IP destino — Nó 3 (apenas para cliente/Nó 1)")
    parser.add_argument("--bind",     default="0.0.0.0",
                        help="IP de bind do servidor")
    parser.add_argument("--duration", type=int,   default=15)
    parser.add_argument("--pktsize",  type=int,   default=1316,
                        help="Tamanho do payload em bytes (1316=mpegts)")
    parser.add_argument("--label",    default="test",
                        help="Label do ficheiro JSON (só servidor)")
    parser.add_argument("--topology", default="direct",
                        choices=["direct","relay"],
                        help="Topologia (só servidor)")
    parser.add_argument("--rate",     type=int, default=0,
                        help=f"Taxa em kbps (0=auto {DEFAULT_RATE}kbps, só cliente)")
    args = parser.parse_args()

    if args.mode == "server":
        server_mode(args.bind, args.label, args.topology)
    else:
        client_mode(args.target, args.duration, args.pktsize, args.rate)
