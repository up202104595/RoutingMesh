#!/usr/bin/env python3
"""
rtt_test.py — RTT measurement tool for RA-TDMAs+ mesh
Sends PING packets over the TUN network and measures round-trip time.

Usage:
  Node 3 (base):  python3 rtt_test.py --mode server
  Node 3 (base):  python3 rtt_test.py --mode client --target 10.0.0.1 --count 100 --label "P2P_N3toN1"
  Node 3 (base):  python3 rtt_test.py --mode client --target 10.0.0.1 --count 100 --label "RELAY_N3toN1_viaN2" --topology relay

Results saved to: rtt_results_<label>.json
"""

import socket
import time
import json
import argparse
import statistics
import struct
import os

PING_PORT   = 19876
PING_MAGIC  = b"RTTEST"
BUF_SIZE    = 64

def server_mode(bind_ip="0.0.0.0"):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((bind_ip, PING_PORT))
    print(f"[RTT-SERVER] Listening on {bind_ip}:{PING_PORT}")
    while True:
        data, addr = sock.recvfrom(BUF_SIZE)
        if data[:len(PING_MAGIC)] == PING_MAGIC:
            sock.sendto(data, addr)  # echo back

def client_mode(target, count, interval, label, topology):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(2.0)

    rtts = []
    lost = 0
    seq  = 0

    print(f"[RTT-CLIENT] Target={target}:{PING_PORT}  Count={count}  Label={label}")
    print(f"{'SEQ':>5}  {'RTT(ms)':>10}  {'STATUS':>8}")
    print("-" * 30)

    for i in range(count):
        seq += 1
        payload = PING_MAGIC + struct.pack(">HQ", seq, 0)
        t_send = time.perf_counter()
        # encode send timestamp into packet
        payload = PING_MAGIC + struct.pack(">Hd", seq, t_send)
        try:
            sock.sendto(payload, (target, PING_PORT))
            data, _ = sock.recvfrom(BUF_SIZE)
            t_recv = time.perf_counter()
            if data[:len(PING_MAGIC)] == PING_MAGIC:
                _, t_orig = struct.unpack_from(">Hd", data, len(PING_MAGIC))
                rtt_ms = (t_recv - t_orig) * 1000
                rtts.append(rtt_ms)
                print(f"{seq:>5}  {rtt_ms:>10.3f}  {'OK':>8}")
            else:
                lost += 1
                print(f"{seq:>5}  {'---':>10}  {'CORRUPT':>8}")
        except socket.timeout:
            lost += 1
            print(f"{seq:>5}  {'---':>10}  {'TIMEOUT':>8}")

        time.sleep(interval)

    sock.close()

    if not rtts:
        print("\n[RTT-CLIENT] No responses received.")
        return

    avg   = statistics.mean(rtts)
    mn    = min(rtts)
    mx    = max(rtts)
    stdev = statistics.stdev(rtts) if len(rtts) > 1 else 0.0
    # jitter = mean absolute deviation between consecutive samples
    jitter = statistics.mean(abs(rtts[i] - rtts[i-1]) for i in range(1, len(rtts))) if len(rtts) > 1 else 0.0
    pdr    = len(rtts) / count * 100

    print("\n" + "=" * 50)
    print(f"  Label:    {label}")
    print(f"  Topology: {topology}")
    print(f"  Target:   {target}")
    print(f"  Sent:     {count}")
    print(f"  Received: {len(rtts)}  Lost: {lost}")
    print(f"  PDR:      {pdr:.1f}%")
    print(f"  RTT avg:  {avg:.3f} ms")
    print(f"  RTT min:  {mn:.3f} ms")
    print(f"  RTT max:  {mx:.3f} ms")
    print(f"  RTT std:  {stdev:.3f} ms")
    print(f"  Jitter:   {jitter:.3f} ms")
    print("=" * 50)

    result = {
        "label":     label,
        "topology":  topology,
        "target":    target,
        "count":     count,
        "received":  len(rtts),
        "lost":      lost,
        "pdr_pct":   round(pdr, 2),
        "avg_ms":    round(avg, 3),
        "min_ms":    round(mn, 3),
        "max_ms":    round(mx, 3),
        "std_ms":    round(stdev, 3),
        "jitter_ms": round(jitter, 3),
        "samples":   [round(r, 3) for r in rtts],
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    fname = f"rtt_results_{label}.json"
    with open(fname, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\n  Saved → {fname}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode",     choices=["client","server"], required=True)
    parser.add_argument("--target",   default="10.0.0.1")
    parser.add_argument("--count",    type=int,   default=100)
    parser.add_argument("--interval", type=float, default=0.1,
                        help="Seconds between pings (default 0.1 = 10Hz)")
    parser.add_argument("--label",    default="test")
    parser.add_argument("--topology", default="direct",
                        choices=["direct","relay","3hop"])
    args = parser.parse_args()

    if args.mode == "server":
        server_mode()
    else:
        client_mode(args.target, args.count, args.interval, args.label, args.topology)
