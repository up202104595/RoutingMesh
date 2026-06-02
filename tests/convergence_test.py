#!/usr/bin/env python3
"""
convergence_test.py — Topology convergence time measurement

Measures how long it takes from a link break until packets are again
delivered via the new (relay) path.  Run on the base station (Node 3).

Procedure:
  1. Script sends continuous PING packets to Node 1 (robot).
  2. Operator physically moves robot out of range of Node 3 (or blocks with
     iptables) — link N1-N3 breaks.
  3. Script detects the first timeout and starts the convergence timer.
  4. Script records the RTT of the first successful reply (via N2 relay).
  5. Convergence time = time from first timeout to first successful reply.

Usage:
  python3 convergence_test.py --target 10.0.0.1 --label "handoff_test_1"

Results saved to: convergence_<label>.json
"""

import socket
import time
import json
import struct
import argparse
import statistics

PING_PORT  = 19876
PING_MAGIC = b"RTTEST"
BUF_SIZE   = 64

def run_convergence_test(target, label, duration=120, interval=0.1):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.5)

    print(f"[CONV] Target={target}  Label={label}")
    print(f"[CONV] Sending continuous pings — move robot out of range when ready")
    print(f"[CONV] Ctrl+C to stop early\n")

    events      = []
    seq         = 0
    was_alive   = True
    broke_at    = None
    converged_at = None
    conv_rtt    = None
    rtts_before = []
    rtts_after  = []

    start = time.perf_counter()
    try:
        while time.perf_counter() - start < duration:
            seq += 1
            t_send = time.perf_counter()
            payload = PING_MAGIC + struct.pack(">Hd", seq, t_send)
            try:
                sock.sendto(payload, (target, PING_PORT))
                data, _ = sock.recvfrom(BUF_SIZE)
                t_recv  = time.perf_counter()
                rtt_ms  = (t_recv - t_send) * 1000

                if not was_alive and broke_at is not None and converged_at is None:
                    converged_at = t_recv
                    conv_rtt     = rtt_ms
                    conv_time_ms = (converged_at - broke_at) * 1000
                    print(f"\n[CONV] *** CONVERGED after {conv_time_ms:.0f} ms  (RTT={rtt_ms:.1f}ms) ***\n")
                    events.append({"event": "converged", "elapsed_s": round(t_recv - start, 3),
                                   "convergence_ms": round(conv_time_ms, 1), "rtt_ms": round(rtt_ms, 3)})

                was_alive = True
                if broke_at is None:
                    rtts_before.append(rtt_ms)
                elif converged_at is not None:
                    rtts_after.append(rtt_ms)

                rel = time.perf_counter() - start
                status = "RELAY" if (broke_at and converged_at) else ("BREAK" if broke_at else "OK")
                print(f"\r[{rel:6.1f}s] seq={seq:4d}  RTT={rtt_ms:7.2f}ms  {status}   ", end="", flush=True)

            except socket.timeout:
                t_now = time.perf_counter()
                if was_alive:
                    broke_at  = t_now
                    was_alive = False
                    print(f"\n[CONV] *** LINK BREAK detected at {t_now - start:.2f}s ***")
                    events.append({"event": "link_break", "elapsed_s": round(t_now - start, 3)})
                else:
                    rel = time.perf_counter() - start
                    print(f"\r[{rel:6.1f}s] seq={seq:4d}  RTT={'TIMEOUT':>10}  WAIT   ", end="", flush=True)

            time.sleep(max(0, interval - 0.001))

    except KeyboardInterrupt:
        print("\n[CONV] Stopped by user")

    sock.close()
    print()

    result = {
        "label":        label,
        "target":       target,
        "timestamp":    time.strftime("%Y-%m-%dT%H:%M:%S"),
        "events":       events,
    }

    if rtts_before:
        result["rtt_before"] = {
            "count": len(rtts_before),
            "avg_ms":  round(statistics.mean(rtts_before), 3),
            "min_ms":  round(min(rtts_before), 3),
            "max_ms":  round(max(rtts_before), 3),
            "std_ms":  round(statistics.stdev(rtts_before), 3) if len(rtts_before) > 1 else 0,
        }

    if rtts_after:
        result["rtt_after"] = {
            "count": len(rtts_after),
            "avg_ms":  round(statistics.mean(rtts_after), 3),
            "min_ms":  round(min(rtts_after), 3),
            "max_ms":  round(max(rtts_after), 3),
            "std_ms":  round(statistics.stdev(rtts_after), 3) if len(rtts_after) > 1 else 0,
        }

    if broke_at and converged_at:
        result["convergence_ms"] = round((converged_at - broke_at) * 1000, 1)
        result["convergence_rtt_ms"] = round(conv_rtt, 3)
        print(f"[CONV] Convergence time: {result['convergence_ms']} ms")
    elif broke_at:
        print("[CONV] Link broke but never recovered within test duration")
        result["convergence_ms"] = None

    fname = f"convergence_{label}.json"
    with open(fname, "w") as f:
        json.dump(result, f, indent=2)
    print(f"[CONV] Saved → {fname}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--target",   default="10.0.0.1")
    parser.add_argument("--label",    default="handoff_1")
    parser.add_argument("--duration", type=int, default=120,
                        help="Max test duration in seconds")
    parser.add_argument("--interval", type=float, default=0.1,
                        help="Ping interval in seconds")
    args = parser.parse_args()
    run_convergence_test(args.target, args.label, args.duration, args.interval)
