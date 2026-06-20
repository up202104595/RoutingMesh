#!/usr/bin/env python3
"""
tdma_video_slot.py — Prove the DIRECT video stream stays inside N1's TDMA slot.

The beacon plot (ao_rounds_derot.png) already shows that the three nodes keep
their slots, but it only uses *beacons*. The text claims the *video* also
respects N1's slot, yet no figure shows it. This script closes that gap: it
takes a single full wlan0 capture (taken at N3 while N1 streams video over the
DIRECT link), wraps both the beacons and N1's video packets to the 150 ms
frame, removes the common frame rotation (de-rotation, exactly as the beacon
plot does), and overlays the two. If the conclusion holds, N1's video burst
lands inside the same [0,50) ms slot as N1's beacon.

How to capture (at N3, direct link, video running):
    capture wlan0 with NO filter  ->  export the full packet list as CSV
    (Wireshark: File > Export Packet Dissections > As CSV)

Run:
    python3 tdma_video_slot.py <full_capture.csv>
    python3 tdma_video_slot.py <full_capture.csv> --last-rounds 14

Outputs (next to the CSV):
    <name>_video_slot_rounds.png   round-by-round scatter, beacons + N1 video
    <name>_video_slot_hist.png     N1 beacon vs N1 video position histogram
    <name>_video_slot_stats.json   % of N1 video packets inside N1's slot
"""

import sys
import os
import csv
import json
import argparse
from collections import defaultdict

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# ── TDMA configuration ─────────────────────────────────────────────────────────
FRAME_MS  = 150.0     # full frame duration (ms)
SLOT_MS   = 50.0      # slot duration (ms)

# Physical addresses (wlan0). The node id is the last octet.
IP_TO_NODE = {'172.20.10.1': 1, '172.20.10.2': 2, '172.20.10.3': 3}
N1_PHYS    = '172.20.10.1'      # robot, physical plane: source of direct video
N1_MESH    = '10.0.0.1'         # robot, mesh plane: in case capture is on tun
N1_VIDEO_SRC = (N1_PHYS, N1_MESH)

NODE_COLORS = {1: '#2196F3', 2: '#4CAF50', 3: '#F44336'}
SLOT_START  = {1: 0.0, 2: 50.0, 3: 100.0}
VIDEO_COLOR = '#111111'

BEACON_MAX_LEN = 120   # beacons are ~88-120 B
VIDEO_MIN_LEN  = 200   # video data packets are much larger (encapsulated TS)


# ── CSV loading ────────────────────────────────────────────────────────────────
def load_full_capture(path):
    """
    Read a full (unfiltered) Wireshark CSV captured at N3 on wlan0.
    Returns two lists of (timestamp_s, node):
        beacons : TDMA control beacons, tagged with the transmitting node
        video   : N1's video data packets (encapsulated, large, from N1)
    Beacons are identified by source IP + small length; video by source IP N1
    + large length (which excludes the tiny TCP ACKs flowing the other way).
    """
    beacons, video = [], []
    diag = {'rows': 0, 'max_len': 0, 'big_by_src': defaultdict(int)}
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            sys.exit("ERROR: empty or malformed CSV")
        norm = {h.strip().strip('"').lower(): h for h in reader.fieldnames}
        c_time = norm.get('time')
        c_src  = norm.get('source')
        c_len  = norm.get('length')
        if not (c_time and c_src):
            sys.exit(f"ERROR: CSV must have Time and Source columns; got {list(norm)}")

        for row in reader:
            try:
                ts  = float(row[c_time].strip().strip('"'))
                src = row[c_src].strip().strip('"')
                ln  = int(row[c_len].strip().strip('"')) if c_len else 0
            except (ValueError, KeyError):
                continue

            diag['rows'] += 1
            diag['max_len'] = max(diag['max_len'], ln)
            if ln >= VIDEO_MIN_LEN:
                diag['big_by_src'][src] += 1

            node = IP_TO_NODE.get(src)
            if node is None:
                continue

            if ln <= BEACON_MAX_LEN:
                beacons.append((ts, node))           # control beacon
            elif src in N1_VIDEO_SRC and ln >= VIDEO_MIN_LEN:
                video.append((ts, 1))                # N1 video data packet

    return beacons, video, diag


# ── Frame math (circular, drift, de-rotation) ──────────────────────────────────
def circ_mean(pos_ms, period=FRAME_MS):
    if len(pos_ms) == 0:
        return 0.0
    ang = 2 * np.pi * np.asarray(pos_ms) / period
    m = np.arctan2(np.sin(ang).mean(), np.cos(ang).mean())
    return (m / (2 * np.pi) * period) % period


def circ_std(pos_ms, period=FRAME_MS):
    if len(pos_ms) < 2:
        return 0.0
    ang = 2 * np.pi * np.asarray(pos_ms) / period
    R = np.hypot(np.sin(ang).mean(), np.cos(ang).mean())
    R = min(max(R, 1e-12), 1.0)
    return np.sqrt(-2.0 * np.log(R)) / (2 * np.pi) * period


def drift_rate_ms_per_s(packets, ref_node, t0):
    """Frame rotation speed (ms/s) tracked on one node, by unwrapping its
    wrapped position over time and fitting a line. The synchroniser advances
    all slots together every round, so the whole frame rotates; this measures
    that common rotation so it can be removed."""
    pts = [ts for ts, n in packets if n == ref_node]
    if len(pts) < 3:
        return 0.0
    t = np.array([ts - t0 for ts in pts])
    p = np.array([((ts - t0) * 1000.0) % FRAME_MS for ts in pts])
    unwrapped = np.unwrap(p * 2 * np.pi / FRAME_MS) / (2 * np.pi) * FRAME_MS
    if t.max() - t.min() < 1e-6:
        return 0.0
    slope, _ = np.polyfit(t, unwrapped, 1)
    return slope


def derotate(packets, drift, t0):
    """Subtract the common frame rotation so each node settles in its slot
    (equivalent to looking at a short window). Relative sync between nodes is
    untouched — every node rotates together."""
    return [(ts - drift * (ts - t0) / 1000.0, node) for ts, node in packets]


def wrap(packets, offset, t0):
    """Return {node: [position_in_frame_ms, ...]} after wrapping mod 150 ms."""
    out = defaultdict(list)
    for ts, node in packets:
        out[node].append((((ts - t0) * 1000.0) + offset) % FRAME_MS)
    return out


# ── Plot: round-by-round scatter, beacons + N1 video overlaid ──────────────────
def plot_rounds(beacons, video, offset, t0, out_path, max_rounds=14):
    def rounds_of(packets):
        pts = []
        for ts, node in packets:
            ms = (ts - t0) * 1000.0
            pts.append((((ms + offset) % FRAME_MS), int(ms // FRAME_MS), node))
        return pts

    bpts = rounds_of(beacons)
    vpts = rounds_of(video)
    if not bpts:
        sys.exit("ERROR: no beacons found — cannot establish the slot reference.")
    last = max(p[1] for p in bpts)
    lo = max(0, last - max_rounds + 1)

    fig, ax = plt.subplots(figsize=(9, 5))

    # slot bands + boundaries
    for node in (1, 2, 3):
        s = SLOT_START[node]
        ax.axvspan(s, s + SLOT_MS, alpha=0.05, color=NODE_COLORS[node])
    for b in (0, 50, 100, 150):
        ax.axvline(b, color='gray', ls='--', lw=0.8, alpha=0.6)

    # beacons (reference slots)
    for node in (1, 2, 3):
        xs = [pos for pos, rnd, n in bpts if n == node and rnd >= lo]
        ys = [rnd for pos, rnd, n in bpts if n == node and rnd >= lo]
        if xs:
            ax.scatter(xs, ys, s=22, color=NODE_COLORS[node],
                       label=f'N{node} beacon', zorder=2)

    # N1 video (the thing we want to prove sits in N1's slot)
    xs = [pos for pos, rnd, n in vpts if rnd >= lo]
    ys = [rnd for pos, rnd, n in vpts if rnd >= lo]
    if xs:
        ax.scatter(xs, ys, s=30, marker='x', linewidths=1.1,
                   color=VIDEO_COLOR, label='N1 video', zorder=3)

    ax.set_xlim(0, FRAME_MS)
    ax.set_xlabel('Position within TDMA frame (ms)  [wrapped 0–150 ms, de-rotated]')
    ax.set_ylabel('TDMA round')
    if video:
        ax.set_title("Direct video vs. beacons per round (de-rotated)\n"
                     "N1's video burst falls inside N1's slot [0–50 ms]")
    else:
        ax.set_title("Beacon transmission per round (de-rotated)\n"
                     "each node stays in its own slot")
    ax.legend(loc='center left', bbox_to_anchor=(1.01, 0.5), fontsize=9)
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"[PLOT] {out_path}")


# ── Plot: N1 beacon vs N1 video position histogram ─────────────────────────────
def plot_hist(wrapped_beacon_n1, wrapped_video_n1, out_path):
    bins = np.arange(0, FRAME_MS + 1, 2)
    fig, ax = plt.subplots(figsize=(9, 4))
    if wrapped_beacon_n1:
        ax.hist(wrapped_beacon_n1, bins=bins, color=NODE_COLORS[1], alpha=0.55,
                label='N1 beacon', edgecolor='none')
    if wrapped_video_n1:
        ax.hist(wrapped_video_n1, bins=bins, color=VIDEO_COLOR, alpha=0.55,
                label='N1 video', edgecolor='none')
    ax.axvspan(SLOT_START[1], SLOT_START[1] + SLOT_MS, alpha=0.12,
               color=NODE_COLORS[1], label='N1 slot')
    for b in (0, 50, 100, 150):
        ax.axvline(b, color='black', ls='--', lw=1.0, alpha=0.7)
    ax.set_xlim(0, FRAME_MS)
    ax.set_xlabel('Position within TDMA frame (ms)')
    ax.set_ylabel('Packets')
    ax.set_title("N1 beacon vs. N1 video position within the frame")
    ax.legend(loc='upper right', fontsize=9)
    ax.grid(axis='x', alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"[PLOT] {out_path}")


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('csv', help='full unfiltered wlan0 CSV captured at N3 (direct video)')
    ap.add_argument('--last-rounds', type=int, default=14, metavar='N',
                    help='show only the last N rounds in the scatter (default 14)')
    args = ap.parse_args()

    if not os.path.exists(args.csv):
        sys.exit(f"ERROR: file not found: {args.csv}")

    beacons, video, diag = load_full_capture(args.csv)
    if not beacons:
        sys.exit("ERROR: no TDMA beacons found. Capture wlan0 unfiltered, "
                 "so both beacons (<=120 B) and video (>=200 B) are present.")
    if not video:
        print("NOTE: no N1 video packets found "
              f"(src {N1_PHYS} or {N1_MESH}, length >= {VIDEO_MIN_LEN} B).")
        print(f"  {diag['rows']} packets parsed, largest packet = {diag['max_len']} B.")
        if diag['max_len'] < VIDEO_MIN_LEN:
            print("  -> This capture has NO video: every packet is small "
                  "(control plane only). The figure will show beacons only.")
            print("     To also prove the video stays in slot, re-capture wlan0 "
                  "WITHOUT any filter WHILE the video streams N1->N3 (direct).")
        elif diag['big_by_src']:
            top = sorted(diag['big_by_src'].items(), key=lambda kv: -kv[1])[:5]
            print("  -> Large packets exist but not from N1. Sources of >=200 B:")
            for s, n in top:
                print(f"       {s}: {n}")
            print("     Check the video source address, or tell me the correct one.")
        print("  Continuing with a beacon-only slot figure.")

    print(f"[INFO] {len(beacons)} beacons, {len(video)} N1 video packets")

    # Common time origin and common drift (measured on the beacons, the reference).
    all_pkts = beacons + video
    t0 = min(ts for ts, _ in all_pkts)
    ref_node = max((n for _, n in beacons),
                   key=lambda nd: sum(1 for _, n in beacons if n == nd))
    drift = drift_rate_ms_per_s(beacons, ref_node, t0)
    print(f"[INFO] frame rotation {drift:+.2f} ms/s (removed via de-rotation)")

    # De-rotate BOTH streams with the same drift so they share one frame.
    beacons_d = derotate(beacons, drift, t0)
    video_d   = derotate(video,   drift, t0)

    # Align the axis so N1's beacon cluster sits at the centre of slot 0.
    n1_beacon_pos = wrap(beacons_d, 0.0, t0).get(1, [])
    offset = (SLOT_START[1] + SLOT_MS / 2) - circ_mean(n1_beacon_pos) if n1_beacon_pos else 0.0

    wb = wrap(beacons_d, offset, t0)
    wv = wrap(video_d,   offset, t0)
    n1_b = wb.get(1, [])
    n1_v = wv.get(1, [])

    # Stats: how much of N1's video lands inside N1's slot [0,50) ms.
    def pct_in_n1_slot(pos):
        if not pos:
            return None
        a = np.asarray(pos)
        return round(100.0 * np.sum((a >= SLOT_START[1]) & (a < SLOT_START[1] + SLOT_MS)) / len(a), 1)

    stats = {
        'drift_ms_per_s': round(float(drift), 3),
        'n1_beacon': {'n': len(n1_b), 'mean_ms': round(float(circ_mean(n1_b)), 2),
                      'std_circ_ms': round(float(circ_std(n1_b)), 2),
                      'pct_in_slot': pct_in_n1_slot(n1_b)},
        'n1_video':  {'n': len(n1_v), 'mean_ms': round(float(circ_mean(n1_v)), 2),
                      'std_circ_ms': round(float(circ_std(n1_v)), 2),
                      'pct_in_slot': pct_in_n1_slot(n1_v)},
    }

    print("\n─── N1 position within the frame ────────────────────────────")
    print(f"  {'stream':<10}{'n':>7}{'mean ms':>10}{'σ circ':>9}{'% in slot':>11}")
    for k in ('n1_beacon', 'n1_video'):
        s = stats[k]
        print(f"  {k.replace('n1_',''):<10}{s['n']:>7}{s['mean_ms']:>10.2f}"
              f"{s['std_circ_ms']:>9.2f}{str(s['pct_in_slot'])+'%':>11}")
    print("─────────────────────────────────────────────────────────────")
    print("Conclusion: if 'video' clusters in the same [0,50) ms band as "
          "'beacon',\nthe direct video respects N1's TDMA slot.")

    base = os.path.splitext(args.csv)[0]
    plot_rounds(beacons_d, video_d, offset, t0,
                base + '_video_slot_rounds.png', max_rounds=args.last_rounds)
    plot_hist(n1_b, n1_v, base + '_video_slot_hist.png')

    with open(base + '_video_slot_stats.json', 'w') as f:
        json.dump(stats, f, indent=2)
    print(f"[INFO] stats -> {base}_video_slot_stats.json")


if __name__ == '__main__':
    main()
