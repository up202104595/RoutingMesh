#!/usr/bin/env python3
"""
csv_throughput.py — Application-level video throughput from Wireshark CSVs.

Measures the throughput of the video ACTUALLY DELIVERED to the base station
(the MPEG-TS / UDP flow to 10.0.0.3:5000). This is the fair, comparable metric
for direct vs relay, because in BOTH cases it counts the same thing: the video
the application receives.

It deliberately does NOT count the wire-level encapsulated stream (TDMA TCP in
direct, raw MPEG-TS in relay), which differs between the two and is not
comparable — counting that would wrongly suggest the relay halves throughput.

Usage:
  python3 csv_throughput.py direct.csv relay.csv --out figs/throughput_time.png
  python3 csv_throughput.py ao.csv rel.csv --out figs/throughput_time.png
"""

import sys, os, csv, argparse
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

DST_VIDEO = '10.0.0.3'   # base station (mesh IP)
SRC_VIDEO = '10.0.0.1'   # robot (mesh IP)
HDR_BYTES = 42           # eth(14)+ip(20)+udp(8) — payload ≈ length - HDR_BYTES


def load_video(path):
    """Return (t_seconds, payload_bytes, proto_counts) of the delivered video
    packets (MPEG-TS / large UDP from the robot to the base station).

    proto_counts (the protocol seen on the matched packets) is what proves the
    relay is transparent: a relayed flow shows up as raw 'MPEG TS' / 'UDP', i.e.
    NOT re-encapsulated in the TDMA framing — it is a direct IP forward."""
    from collections import Counter
    ts, ln = [], []
    proto_counts = Counter()
    with open(path, newline='', encoding='utf-8-sig') as f:
        r = csv.DictReader(f)
        norm = {h.strip().strip('"').lower(): h for h in (r.fieldnames or [])}
        tc, sc, dc = norm.get('time'), norm.get('source'), norm.get('destination')
        pc, lc = norm.get('protocol'), norm.get('length')
        if not (tc and sc and dc):
            print(f'ERROR: {path} missing Time/Source/Destination columns'); sys.exit(1)
        for row in r:
            try:
                t = float(row[tc].strip().strip('"'))
                src = row[sc].strip().strip('"')
                dst = row[dc].strip().strip('"')
                proto = row[pc].strip().strip('"').upper() if pc else ''
                L = int(row[lc].strip().strip('"')) if lc else 0
            except (ValueError, KeyError):
                continue
            # delivered video: robot -> base station, MPEG-TS (or large UDP),
            # excludes small telemetry (UDP ~157 B on port 9001) via the size filter
            if src == SRC_VIDEO and dst == DST_VIDEO and \
               ('MPEG TS' in proto or (proto == 'UDP' and L > 200)):
                ts.append(t)
                ln.append(max(0, L - HDR_BYTES))
                proto_counts[proto] += 1
    return np.array(ts), np.array(ln), proto_counts


def main():
    ap = argparse.ArgumentParser(description='Delivered video throughput from CSV (direct vs relay)')
    ap.add_argument('direct', help='direct-link CSV (e.g. ao.csv)')
    ap.add_argument('relay',  help='relay CSV (e.g. rel.csv)')
    ap.add_argument('--out', default='throughput_time.png', help='output PNG')
    ap.add_argument('--bin', type=float, default=1.0, help='time bin (s)')
    ap.add_argument('--title', default=None, help='figure title (default: none)')
    args = ap.parse_args()

    fig, ax = plt.subplots(figsize=(11, 5))
    for label, path, color in [('Direct (N1→N3)', args.direct, '#2196F3'),
                               ('Relay (N1→N2→N3)', args.relay, '#2E7D32')]:
        ts, ln, protos = load_video(path)
        if len(ts) < 2:
            print(f'[WARN] {path}: only {len(ts)} delivered-video packets found.')
            print('       (the capture may not include the tun0 MPEG-TS flow to 10.0.0.3:5000)')
            continue
        ts = ts - ts[0]
        dur = ts[-1]
        mean_kbps = ln.sum() * 8 / 1000.0 / dur
        edges = np.arange(0, dur + args.bin, args.bin)
        b, _ = np.histogram(ts, bins=edges, weights=ln)
        kbps = b * 8 / 1000.0 / args.bin
        centers = (edges[:-1] + edges[1:]) / 2
        ax.plot(centers, kbps, color=color, lw=1.6,
                label=f'{label}  (avg {mean_kbps:.0f} kbps)')
        ax.axhline(mean_kbps, color=color, ls=':', lw=1, alpha=0.7)
        proto_str = ', '.join(f'{p}:{c}' for p, c in protos.most_common())
        print(f'  {label:>16}: {len(ts):>5} pkts  {dur:5.0f}s  mean {mean_kbps:.1f} kbps'
              f'  [protocols → {proto_str}]')

    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Delivered video throughput (kbps)')
    ax.set_ylim(bottom=0)
    ax.set_xlim(left=0)
    ax.legend(fontsize=10, loc='center right')
    ax.grid(alpha=0.3)
    if args.title:
        ax.set_title(args.title, fontsize=12, fontweight='bold')
    plt.tight_layout()
    os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)
    plt.savefig(args.out, dpi=150)
    plt.close()
    print(f'[PLOT] {args.out}')


if __name__ == '__main__':
    main()
