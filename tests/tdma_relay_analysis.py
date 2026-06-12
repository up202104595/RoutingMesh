#!/usr/bin/env python3
"""
tdma_relay_analysis.py — Análise de cenário relay TDMA

Diferença do tdma_sync_plot.py:
  Identifica o emissor ORIGINAL via src_id no payload MSG_DATA,
  independentemente do IP/nó que fez o relay.
  O IP de origem diz QUEM fez relay; o src_id diz QUEM gerou os dados.

Formatos suportados:
  .pcap / .pcapng  — lê payload UDP via scapy, extrai src_id do MSG_DATA
                     (requer: pip3 install scapy)
  .csv             — exportado do Wireshark; tenta extrair srcport da
                     coluna Info como fallback (menos preciso)

Wire format esperado (MSG_DATA, type=2):
  [ tdma_header_t (18 B) ][ msg_data_hdr_t header (6 B) ][ IP payload ]

Uso:
  python3 tdma_relay_analysis.py <ficheiro.pcap>
  python3 tdma_relay_analysis.py <ficheiro.csv>

Nota para CSV: capturar sem filtro de length (o relay encaminha pacotes
  de tamanho variável, não apenas os beacons de 107 bytes).
"""

import sys
import os
import csv
import json
import re
import struct
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from collections import defaultdict

# ── Configuração TDMA ──────────────────────────────────────────────────────────
FRAME_MS  = 150.0
SLOT_MS   = 50.0
NUM_NODES = 3
MSG_DATA  = 2   # tdma_header_t.type

# tdma_header_t (packed, little-endian):
#   uint8_t  type          1
#   uint8_t  slot_id       1
#   uint32_t seq_num       4
#   double   timestamp     8
#   uint16_t slot_begin_ms 2
#   uint16_t slot_end_ms   2   → total 18 bytes
TDMA_HDR_FMT  = '<BBIdHH'
TDMA_HDR_SIZE = struct.calcsize(TDMA_HDR_FMT)   # 18

# msg_data_hdr_t fixed header (packed, little-endian):
#   uint8_t  src_id  1
#   uint8_t  dst_id  1
#   uint16_t msg_id  2
#   uint16_t data_len 2  → total 6 bytes
MSG_HDR_FMT  = '<BBHH'
MSG_HDR_SIZE = struct.calcsize(MSG_HDR_FMT)      # 6
MIN_PKT_SIZE = TDMA_HDR_SIZE + MSG_HDR_SIZE       # 24

RELAY_IP_TO_NODE = {'172.20.10.1': 1, '172.20.10.2': 2, '172.20.10.3': 3}
SRCPORT_TO_NODE  = {7001: 1, 7002: 2, 7003: 3}

NODE_COLORS = {0: '#888888', 1: '#2196F3', 2: '#4CAF50', 3: '#F44336'}
SLOT_START  = {1: 0.0, 2: 50.0, 3: 100.0}


# ── Parsing pcap (src_id exacto do payload) ────────────────────────────────────
def load_pcap(path):
    try:
        from scapy.all import rdpcap, UDP, IP
    except ImportError:
        print("ERRO: scapy não instalado. Instala com: pip3 install scapy")
        sys.exit(1)

    print(f"[INFO] A ler pcap: {path}")
    pkts    = rdpcap(path)
    records = []
    t0      = None
    skipped = 0

    for pkt in pkts:
        if UDP not in pkt or IP not in pkt:
            continue
        sport = pkt[UDP].sport
        dport = pkt[UDP].dport
        if sport not in SRCPORT_TO_NODE and dport not in SRCPORT_TO_NODE:
            continue

        payload = bytes(pkt[UDP].payload)
        if len(payload) < MIN_PKT_SIZE:
            skipped += 1
            continue

        try:
            pkt_type, slot_id, seq_num, timestamp, slot_begin_ms, slot_end_ms = \
                struct.unpack_from(TDMA_HDR_FMT, payload, 0)
        except struct.error:
            skipped += 1
            continue

        if pkt_type != MSG_DATA:
            continue

        try:
            src_id, dst_id, msg_id, data_len = \
                struct.unpack_from(MSG_HDR_FMT, payload, TDMA_HDR_SIZE)
        except struct.error:
            skipped += 1
            continue

        if src_id == 0 or src_id > 20:
            skipped += 1
            continue

        relay_node = RELAY_IP_TO_NODE.get(pkt[IP].src, 0)

        ts = float(pkt.time)
        if t0 is None:
            t0 = ts
        ts_ms = (ts - t0) * 1000.0

        records.append({
            'ts_ms':         ts_ms,
            'frame_pos':     ts_ms % FRAME_MS,
            'original_node': src_id,
            'dst_node':      dst_id,
            'relay_node':    relay_node,
            'relay_ip':      pkt[IP].src,
            'slot_begin':    slot_begin_ms,
            'slot_end':      slot_end_ms,
            'seq_num':       seq_num,
        })

    if skipped:
        print(f"[WARN] {skipped} pacotes ignorados (tamanho, parse, não MSG_DATA)")
    return records


# ── Parsing CSV (srcport da coluna Info como proxy do emissor original) ────────
def _srcport_from_info(info_str):
    """Extrai source port de strings tipo '7001 → 7002  Len=…' ou '7001 > 7002'."""
    m = re.search(r'(\d{4,5})\s*[→>-]+\s*\d{4,5}', info_str)
    if m:
        return int(m.group(1))
    return None


def load_csv(path):
    print(f"[INFO] A ler CSV Wireshark: {path}")
    print("[WARN] Modo CSV: usa srcport como proxy do emissor original.")
    print("       Para análise exacta usa ficheiro .pcap com scapy.")
    records = []
    t0      = None
    skipped = 0

    with open(path, newline='', encoding='utf-8-sig') as f:
        reader  = csv.DictReader(f)
        headers = reader.fieldnames
        if not headers:
            print("ERRO: CSV vazio")
            sys.exit(1)

        norm      = {h.strip().lower(): h for h in headers}
        time_col  = norm.get('time')
        src_col   = norm.get('source')
        info_col  = norm.get('info')
        proto_col = norm.get('protocol')

        if not time_col or not src_col:
            print("ERRO: colunas Time/Source não encontradas")
            sys.exit(1)

        for row in reader:
            try:
                ts  = float(row[time_col].strip())
                src = row[src_col].strip()
            except (ValueError, KeyError):
                continue

            if proto_col:
                proto = row[proto_col].strip().upper()
                if proto not in ('UDP', 'RX'):
                    continue

            relay_node = RELAY_IP_TO_NODE.get(src, 0)
            if relay_node == 0:
                skipped += 1
                continue

            # Tenta obter emissor original via srcport
            original_node = 0
            if info_col:
                sport = _srcport_from_info(row[info_col].strip())
                if sport in SRCPORT_TO_NODE:
                    original_node = SRCPORT_TO_NODE[sport]

            # Fallback: assume directo (relay_node = original)
            if original_node == 0:
                original_node = relay_node

            if t0 is None:
                t0 = ts
            ts_ms = (ts - t0) * 1000.0

            records.append({
                'ts_ms':         ts_ms,
                'frame_pos':     ts_ms % FRAME_MS,
                'original_node': original_node,
                'dst_node':      0,
                'relay_node':    relay_node,
                'relay_ip':      src,
                'slot_begin':    None,
                'slot_end':      None,
                'seq_num':       None,
            })

    if skipped:
        print(f"[WARN] {skipped} pacotes ignorados (IP desconhecido)")
    return records


# ── Estatísticas ───────────────────────────────────────────────────────────────
def compute_stats(records):
    groups = defaultdict(list)
    for r in records:
        groups[(r['original_node'], r['relay_node'])].append(r['frame_pos'])

    print("\n─── Análise de Relay TDMA ────────────────────────────────────────────────────")
    print(f"  {'Origem':>6}  {'Relay (fwd)':>12}  {'N pkts':>7}  "
          f"{'μ pos (ms)':>10}  {'σ (ms)':>7}  {'% no slot orig.':>16}")
    print("─" * 72)

    results = {}
    for (orig, relay) in sorted(groups.keys()):
        pos = np.array(groups[(orig, relay)])
        mu  = np.mean(pos)
        sig = np.std(pos)
        sl_s = SLOT_START.get(orig, -1)
        inside = np.sum((pos >= sl_s) & (pos < sl_s + SLOT_MS)) if sl_s >= 0 else 0
        pct    = 100.0 * inside / len(pos) if len(pos) else 0.0

        if relay == orig:
            relay_label = f'N{relay} (direto)'
        else:
            relay_label = f'N{relay} (relay)'

        print(f"  N{orig}       {relay_label:>13}  {len(pos):>7}  "
              f"{mu:>10.2f}  {sig:>7.2f}  {pct:>15.1f}%")

        results[f'N{orig}_via_N{relay}'] = {
            'original': orig, 'relay': relay,
            'n': len(pos), 'mean_ms': round(mu, 2),
            'std_ms': round(sig, 2), 'pct_in_orig_slot': round(pct, 1),
        }

    print("─" * 72)
    return results, groups


# ── Plot 1: Histograma por emissor ORIGINAL ────────────────────────────────────
def plot_histogram(groups, out_path):
    by_orig = defaultdict(list)
    for (orig, relay), pos in groups.items():
        by_orig[orig].extend(pos)

    bins = np.arange(0, FRAME_MS + 1, 1)
    fig, axes = plt.subplots(NUM_NODES, 1, figsize=(12, 8), sharex=True)
    fig.suptitle(
        'Relay TDMA — distribuição por EMISSOR ORIGINAL (não pelo IP de relay)',
        fontsize=11, fontweight='bold')

    for i, node in enumerate([1, 2, 3]):
        ax  = axes[i]
        pos = by_orig.get(node, [])
        col = NODE_COLORS[node]

        if pos:
            ax.hist(pos, bins=bins, color=col, alpha=0.8, edgecolor='none')
            mu = np.mean(pos)
            ax.axvline(x=mu, color='orange', lw=1.8,
                       label=f'μ={mu:.1f}ms  σ={np.std(pos):.1f}ms  n={len(pos)}')

        sl_s = SLOT_START[node]
        for b in [0, 50, 100, 150]:
            ax.axvline(x=b, color='black', lw=0.9, linestyle='--', alpha=0.6)
        ax.axvspan(sl_s, sl_s + SLOT_MS, alpha=0.14, color=col,
                   label=f'Slot N{node} ({sl_s:.0f}–{sl_s+SLOT_MS:.0f} ms)')
        ax.set_ylabel(f'N{node}\n(pkts)', fontsize=9)
        ax.legend(loc='upper right', fontsize=8)
        ax.grid(axis='x', alpha=0.3)

    axes[-1].set_xlabel('Posição dentro do frame TDMA (ms)', fontsize=11)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"[PLOT] Histograma por emissor original: {out_path}")


# ── Plot 2: Scatter — emissor original no eixo Y, relay diferenciado por forma ─
def plot_scatter(groups, out_path):
    markers = {0: 'x', 1: 'o', 2: 's', 3: '^'}

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.set_title(
        'Relay TDMA — scatter por emissor original  (forma = nó que fez relay)',
        fontsize=11, fontweight='bold')

    for (orig, relay), positions in sorted(groups.items()):
        pos = positions[-500:] if len(positions) > 500 else positions
        label = f'N{orig} via N{relay}' if relay != orig else f'N{orig} direto'
        ax.scatter(pos, [orig] * len(pos), s=7, alpha=0.5,
                   color=NODE_COLORS.get(orig, '#888'),
                   marker=markers.get(relay, '*'), label=label)

    for b in [0, 50, 100, 150]:
        ax.axvline(x=b, color='black', lw=1.1, linestyle='--', alpha=0.65)
    ax.axvspan(0,   50,  alpha=0.05, color=NODE_COLORS[1])
    ax.axvspan(50,  100, alpha=0.05, color=NODE_COLORS[2])
    ax.axvspan(100, 150, alpha=0.05, color=NODE_COLORS[3])

    ax.set_xlim(0, FRAME_MS)
    ax.set_ylim(0.5, NUM_NODES + 0.5)
    ax.set_yticks([1, 2, 3])
    ax.set_yticklabels(['N1 (orig.)', 'N2 (orig.)', 'N3 (orig.)'])
    ax.set_xlabel('Posição dentro do frame TDMA (ms)', fontsize=11)
    ax.legend(loc='upper right', fontsize=8, markerscale=2)
    ax.grid(axis='x', alpha=0.3)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"[PLOT] Scatter relay: {out_path}")


# ── Plot 3: Mapa de relay (diagrama de setas) ──────────────────────────────────
def plot_relay_map(records, out_path):
    import math

    counts = defaultdict(int)
    for r in records:
        counts[(r['original_node'], r['relay_node'])] += 1

    nodes = sorted({r['original_node'] for r in records} |
                   {r['relay_node'] for r in records if r['relay_node'] != 0})

    fig, ax = plt.subplots(figsize=(6, 5))
    ax.set_title('Mapa de relay: quem encaminha pacotes de quem', fontsize=11)
    ax.set_aspect('equal')
    ax.axis('off')
    ax.set_xlim(-1.1, 1.1)
    ax.set_ylim(-1.1, 1.1)

    # Posições em triângulo
    n = len(nodes)
    pos = {}
    for i, nd in enumerate(nodes):
        angle = math.pi / 2 + i * (2 * math.pi / n)
        pos[nd] = (math.cos(angle) * 0.65, math.sin(angle) * 0.65)

    max_cnt = max(counts.values()) if counts else 1

    for (orig, relay), cnt in sorted(counts.items()):
        if orig not in pos or (relay != 0 and relay not in pos):
            continue
        x0, y0 = pos[orig]
        x1, y1 = pos.get(relay, pos[orig])
        lw = 1.5 + 3.5 * cnt / max_cnt
        col = NODE_COLORS.get(orig, '#888')

        if orig == relay:
            # Tráfego directo — seta curta sobre o próprio nó
            ax.annotate('direto', xy=(x0, y0 + 0.18), xytext=(x0, y0 + 0.32),
                        ha='center', fontsize=7, color=col,
                        arrowprops=dict(arrowstyle='->', color=col, lw=1.2))
        else:
            rad = 0.25 if (relay, orig) in counts else 0.0
            ax.annotate('',
                xy=(x1, y1), xytext=(x0, y0),
                arrowprops=dict(
                    arrowstyle='->', color=col, lw=lw,
                    connectionstyle=f'arc3,rad={rad}'))
            mid_x = (x0 + x1) / 2 + (0.12 if rad else 0)
            mid_y = (y0 + y1) / 2 + (0.08 if rad else 0)
            ax.text(mid_x, mid_y, f'{cnt} pkts', fontsize=7,
                    ha='center', color=col, fontweight='bold')

    for nd, (x, y) in pos.items():
        circle = plt.Circle((x, y), 0.13, color=NODE_COLORS.get(nd, '#888'), zorder=5)
        ax.add_patch(circle)
        ax.text(x, y, f'N{nd}', ha='center', va='center',
                fontsize=12, fontweight='bold', color='white', zorder=6)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"[PLOT] Mapa relay: {out_path}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    path = sys.argv[1]
    if not os.path.exists(path):
        print(f"ERRO: ficheiro não encontrado: {path}")
        sys.exit(1)

    ext = os.path.splitext(path)[1].lower()
    if ext in ('.pcap', '.pcapng'):
        records = load_pcap(path)
    else:
        records = load_csv(path)

    if not records:
        print("ERRO: nenhum pacote MSG_DATA encontrado.")
        print("  .pcap: confirma tráfego UDP 7001-7003 com cabeçalho MSG_DATA (type=2)")
        print("  .csv:  exporta do Wireshark SEM filtro de length (pacotes de tamanho variável)")
        sys.exit(1)

    print(f"[INFO] {len(records)} pacotes carregados")
    orig_nodes  = sorted({r['original_node'] for r in records})
    relay_nodes = sorted({r['relay_node'] for r in records
                          if r['relay_node'] not in (0, r['original_node'])})
    print(f"[INFO] Emissores originais detectados: {orig_nodes}")
    if relay_nodes:
        print(f"[INFO] Nós relay detectados: {relay_nodes}")
    else:
        print("[INFO] Nenhum relay detectado — tudo tráfego directo")

    stats, groups = compute_stats(records)

    base = os.path.splitext(path)[0]
    plot_histogram(groups, base + '_relay_histogram.png')
    plot_scatter(groups, base + '_relay_scatter.png')
    plot_relay_map(records, base + '_relay_map.png')

    json_path = base + '_relay_stats.json'
    with open(json_path, 'w') as f:
        json.dump(stats, f, indent=2)
    print(f"[INFO] Estatísticas JSON: {json_path}")


if __name__ == '__main__':
    main()
