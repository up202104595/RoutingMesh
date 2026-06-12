#!/usr/bin/env python3
"""
tdma_relay_analysis.py — Análise de cenário relay TDMA

Identifica o emissor ORIGINAL via src_id no payload MSG_DATA,
independentemente do IP/nó que fez o relay.

Sem dependências externas — lê pcap/pcapng em Python puro.

Formatos suportados:
  .pcap / .pcapng  — leitura directa (sem scapy)
  .csv             — exportado do Wireshark (srcport da coluna Info como proxy;
                     menos preciso que pcap)

Wire format esperado (MSG_DATA, type=2):
  [ tdma_header_t (18 B) ][ msg_data_hdr_t header (6 B) ][ IP payload ]

Uso:
  python3 tdma_relay_analysis.py <ficheiro.pcap>
  python3 tdma_relay_analysis.py <ficheiro.pcapng>
  python3 tdma_relay_analysis.py <ficheiro.csv>
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
MSG_DATA  = 2

# tdma_header_t (packed, little-endian):
#   uint8_t  type          1
#   uint8_t  slot_id       1
#   uint32_t seq_num       4
#   double   timestamp     8
#   uint16_t slot_begin_ms 2
#   uint16_t slot_end_ms   2   → 18 bytes total
TDMA_HDR_FMT  = '<BBIdHH'
TDMA_HDR_SIZE = struct.calcsize(TDMA_HDR_FMT)   # 18

# msg_data_hdr_t (packed, little-endian):
#   uint8_t  src_id   1
#   uint8_t  dst_id   1
#   uint16_t msg_id   2
#   uint16_t data_len 2   → 6 bytes total
MSG_HDR_SIZE = 6
MIN_PKT_SIZE = TDMA_HDR_SIZE + MSG_HDR_SIZE  # 24

RELAY_IP_TO_NODE = {'172.20.10.1': 1, '172.20.10.2': 2, '172.20.10.3': 3}
SRCPORT_TO_NODE  = {7001: 1, 7002: 2, 7003: 3}
NODE_COLORS      = {0: '#888888', 1: '#2196F3', 2: '#4CAF50', 3: '#F44336'}
SLOT_START       = {1: 0.0, 2: 50.0, 3: 100.0}


# ── Parse Ethernet → IPv4 → UDP ───────────────────────────────────────────────
def _parse_eth_udp(data):
    """Devolve (ip_src_str, sport, dport, udp_payload) ou None."""
    if len(data) < 34:
        return None
    if struct.unpack('>H', data[12:14])[0] != 0x0800:  # só IPv4
        return None
    ip_ihl   = (data[14] & 0x0F) * 4
    ip_proto = data[23]            # IP header offset 9 = offset 14+9 = 23
    if ip_proto != 17:             # só UDP
        return None
    ip_src  = f'{data[26]}.{data[27]}.{data[28]}.{data[29]}'
    udp_off = 14 + ip_ihl
    if len(data) < udp_off + 8:
        return None
    sport, dport = struct.unpack('>HH', data[udp_off:udp_off + 4])
    return ip_src, sport, dport, data[udp_off + 8:]


# ── Parse payload TDMA MSG_DATA ───────────────────────────────────────────────
def _parse_tdma_msg(payload):
    """Devolve (src_id, dst_id, slot_begin, slot_end, seq_num) ou None."""
    if len(payload) < MIN_PKT_SIZE:
        return None
    try:
        pkt_type, _slot_id, seq_num, _ts, slot_begin, slot_end = \
            struct.unpack_from(TDMA_HDR_FMT, payload, 0)
    except struct.error:
        return None
    if pkt_type != MSG_DATA:
        return None
    src_id = payload[TDMA_HDR_SIZE]
    dst_id = payload[TDMA_HDR_SIZE + 1]
    if src_id == 0 or src_id > 20:
        return None
    return src_id, dst_id, slot_begin, slot_end, seq_num


# ── Iterador pcap clássico ────────────────────────────────────────────────────
def _iter_classic_pcap(f):
    """Yields (ts_float, frame_bytes) de um pcap clássico."""
    raw = f.read(4)
    if len(raw) < 4:
        return
    le_magic = struct.unpack('<I', raw)[0]
    if le_magic in (0xa1b2c3d4, 0xa1b23c4d):
        endian  = '<'
        nanosec = (le_magic == 0xa1b23c4d)
    else:
        be_magic = struct.unpack('>I', raw)[0]
        if be_magic in (0xa1b2c3d4, 0xa1b23c4d):
            endian  = '>'
            nanosec = (be_magic == 0xa1b23c4d)
        else:
            print("ERRO: magic pcap inválido — não é um ficheiro pcap clássico")
            return
    gh = f.read(20)
    if len(gh) < 20:
        return
    network = struct.unpack(f'{endian}I', gh[16:20])[0]
    if network != 1:
        print(f"ERRO: link type {network} não suportado (esperado Ethernet=1)")
        return
    div = 1_000_000_000 if nanosec else 1_000_000
    while True:
        hdr = f.read(16)
        if len(hdr) < 16:
            break
        ts_sec, ts_frac, incl_len, _ = struct.unpack(f'{endian}IIII', hdr)
        data = f.read(incl_len)
        if len(data) < incl_len:
            break
        yield ts_sec + ts_frac / div, data


# ── Iterador pcapng ───────────────────────────────────────────────────────────
def _iter_pcapng(f):
    """Yields (ts_float, frame_bytes) de um ficheiro pcapng."""
    # Section Header Block
    raw12 = f.read(12)
    if len(raw12) < 12 or struct.unpack('<I', raw12[0:4])[0] != 0x0A0D0D0A:
        return
    bom = struct.unpack('<I', raw12[8:12])[0]
    if bom == 0x1A2B3C4D:
        endian = '<'
    elif bom == 0x4D3C2B1A:
        endian = '>'
    else:
        return
    shb_len = struct.unpack(f'{endian}I', raw12[4:8])[0]
    f.seek(shb_len - 12, 1)   # salta resto do SHB (já lemos 12 bytes)

    ifaces = {}   # iface_id → (link_type, ts_divisor)

    while True:
        hdr = f.read(8)
        if len(hdr) < 8:
            break
        btype, blen = struct.unpack(f'{endian}II', hdr)
        body = f.read(blen - 12)   # body = total - type(4) - len(4) - trailing_len(4)
        f.read(4)                  # trailing block_len

        if btype == 0x00000001:    # Interface Description Block
            if len(body) >= 2:
                ltype = struct.unpack(f'{endian}H', body[0:2])[0]
                ifaces[len(ifaces)] = (ltype, 1_000_000)   # default: microsegundos

        elif btype == 0x00000006:  # Enhanced Packet Block
            if len(body) < 20:
                continue
            iface_id = struct.unpack(f'{endian}I', body[0:4])[0]
            ts_hi    = struct.unpack(f'{endian}I', body[4:8])[0]
            ts_lo    = struct.unpack(f'{endian}I', body[8:12])[0]
            cap_len  = struct.unpack(f'{endian}I', body[12:16])[0]
            ltype, div = ifaces.get(iface_id, (1, 1_000_000))
            if ltype != 1:   # só Ethernet
                continue
            yield ((ts_hi << 32) | ts_lo) / div, body[20:20 + cap_len]


# ── Carregamento pcap/pcapng ──────────────────────────────────────────────────
def load_pcap(path):
    print(f"[INFO] A ler pcap: {path}")
    records = []
    t0      = None
    skipped = 0

    with open(path, 'rb') as f:
        magic = struct.unpack('<I', f.read(4))[0]
        f.seek(0)
        pkt_iter = _iter_pcapng(f) if magic == 0x0A0D0D0A else _iter_classic_pcap(f)

        for ts, frame in pkt_iter:
            eth = _parse_eth_udp(frame)
            if eth is None:
                continue
            ip_src, sport, dport, payload = eth

            if sport not in SRCPORT_TO_NODE and dport not in SRCPORT_TO_NODE:
                continue

            tdma = _parse_tdma_msg(payload)
            if tdma is None:
                skipped += 1
                continue
            src_id, dst_id, slot_begin, slot_end, seq_num = tdma

            if t0 is None:
                t0 = ts
            ts_ms = (ts - t0) * 1000.0

            records.append({
                'ts_ms':         ts_ms,
                'frame_pos':     ts_ms % FRAME_MS,
                'original_node': src_id,
                'dst_node':      dst_id,
                'relay_node':    RELAY_IP_TO_NODE.get(ip_src, 0),
                'relay_ip':      ip_src,
                'slot_begin':    slot_begin,
                'slot_end':      slot_end,
                'seq_num':       seq_num,
            })

    if skipped:
        print(f"[WARN] {skipped} pacotes ignorados (tamanho insuficiente ou não MSG_DATA)")
    return records


# ── Carregamento CSV (srcport como proxy do emissor) ──────────────────────────
def _srcport_from_info(info):
    m = re.search(r'(\d{4,5})\s*[→>-]+\s*\d{4,5}', info)
    return int(m.group(1)) if m else None


def load_csv(path):
    print(f"[INFO] A ler CSV Wireshark: {path}")
    print("[WARN] Modo CSV: usa srcport como proxy do emissor original.")
    print("       Para análise exacta usa .pcap (sem dependências).")
    records = []
    t0      = None
    skipped = 0

    with open(path, newline='', encoding='utf-8-sig') as f:
        reader  = csv.DictReader(f)
        norm    = {h.strip().lower(): h for h in (reader.fieldnames or [])}
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
            if proto_col and row[proto_col].strip().upper() not in ('UDP', 'RX'):
                continue
            relay_node = RELAY_IP_TO_NODE.get(src, 0)
            if relay_node == 0:
                skipped += 1
                continue

            original_node = 0
            if info_col:
                sp = _srcport_from_info(row[info_col].strip())
                if sp in SRCPORT_TO_NODE:
                    original_node = SRCPORT_TO_NODE[sp]
            if original_node == 0:
                original_node = relay_node

            if t0 is None:
                t0 = ts
            ts_ms = (ts - t0) * 1000.0
            records.append({
                'ts_ms': ts_ms, 'frame_pos': ts_ms % FRAME_MS,
                'original_node': original_node, 'dst_node': 0,
                'relay_node': relay_node, 'relay_ip': src,
                'slot_begin': None, 'slot_end': None, 'seq_num': None,
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
    print(f"  {'Origem':>6}  {'Relay (fwd)':>14}  {'N pkts':>7}  "
          f"{'μ pos (ms)':>10}  {'σ (ms)':>7}  {'% no slot orig.':>16}")
    print("─" * 74)

    results = {}
    for (orig, relay) in sorted(groups.keys()):
        pos   = np.array(groups[(orig, relay)])
        mu    = np.mean(pos)
        sig   = np.std(pos)
        sl_s  = SLOT_START.get(orig, -1)
        pct   = 100.0 * np.sum((pos >= sl_s) & (pos < sl_s + SLOT_MS)) / len(pos) \
                if sl_s >= 0 else 0.0
        label = f'N{relay} (direto)' if relay == orig else f'N{relay} (relay)'
        print(f"  N{orig}       {label:>14}  {len(pos):>7}  "
              f"{mu:>10.2f}  {sig:>7.2f}  {pct:>15.1f}%")
        results[f'N{orig}_via_N{relay}'] = {
            'original': orig, 'relay': relay, 'n': len(pos),
            'mean_ms': round(mu, 2), 'std_ms': round(sig, 2),
            'pct_in_orig_slot': round(pct, 1),
        }

    print("─" * 74)
    return results, groups


# ── Plot 1: Histograma por emissor original ────────────────────────────────────
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


# ── Plot 2: Scatter — emissor original no eixo Y ─────────────────────────────
def plot_scatter(groups, out_path):
    markers = {0: 'x', 1: 'o', 2: 's', 3: '^'}
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.set_title(
        'Relay TDMA — scatter por emissor original  (forma = nó que fez relay)',
        fontsize=11, fontweight='bold')

    for (orig, relay), positions in sorted(groups.items()):
        pos   = positions[-500:] if len(positions) > 500 else positions
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


# ── Plot 3: Mapa de relay ─────────────────────────────────────────────────────
def plot_relay_map(records, out_path):
    import math
    counts = defaultdict(int)
    for r in records:
        counts[(r['original_node'], r['relay_node'])] += 1

    nodes = sorted({r['original_node'] for r in records} |
                   {r['relay_node'] for r in records if r['relay_node'] != 0})
    n = len(nodes)

    fig, ax = plt.subplots(figsize=(6, 5))
    ax.set_title('Mapa de relay: quem encaminha pacotes de quem', fontsize=11)
    ax.set_aspect('equal')
    ax.axis('off')
    ax.set_xlim(-1.1, 1.1)
    ax.set_ylim(-1.1, 1.1)

    pos = {nd: (math.cos(math.pi/2 + i * 2*math.pi/n) * 0.65,
                math.sin(math.pi/2 + i * 2*math.pi/n) * 0.65)
           for i, nd in enumerate(nodes)}

    max_cnt = max(counts.values()) if counts else 1
    for (orig, relay), cnt in sorted(counts.items()):
        if orig not in pos or (relay != 0 and relay not in pos):
            continue
        x0, y0 = pos[orig]
        x1, y1 = pos.get(relay, pos[orig])
        lw  = 1.5 + 3.5 * cnt / max_cnt
        col = NODE_COLORS.get(orig, '#888')
        if orig == relay:
            ax.annotate('direto', xy=(x0, y0 + 0.18), xytext=(x0, y0 + 0.35),
                        ha='center', fontsize=7, color=col,
                        arrowprops=dict(arrowstyle='->', color=col, lw=1.2))
        else:
            rad = 0.25 if (relay, orig) in counts else 0.0
            ax.annotate('', xy=(x1, y1), xytext=(x0, y0),
                        arrowprops=dict(arrowstyle='->', color=col, lw=lw,
                                        connectionstyle=f'arc3,rad={rad}'))
            mid_x = (x0 + x1) / 2 + (0.12 if rad else 0)
            mid_y = (y0 + y1) / 2 + (0.08 if rad else 0)
            ax.text(mid_x, mid_y, f'{cnt} pkts', fontsize=7,
                    ha='center', color=col, fontweight='bold')

    for nd, (x, y) in pos.items():
        ax.add_patch(plt.Circle((x, y), 0.13, color=NODE_COLORS.get(nd, '#888'), zorder=5))
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
        print("  .pcap/pcapng: confirma tráfego UDP 7001-7003 com cabeçalho MSG_DATA (type=2)")
        print("  .csv: exporta sem filtro de length (MSG_DATA tem tamanho variável)")
        sys.exit(1)

    print(f"[INFO] {len(records)} pacotes carregados")
    orig_nodes  = sorted({r['original_node'] for r in records})
    relay_nodes = sorted({r['relay_node'] for r in records
                          if r['relay_node'] not in (0, r['original_node'])})
    print(f"[INFO] Emissores originais detectados: {orig_nodes}")
    if relay_nodes:
        print(f"[INFO] Nós relay detectados: {relay_nodes}")
    else:
        print("[INFO] Sem relay detectado — tudo tráfego directo")

    stats, groups = compute_stats(records)

    base = os.path.splitext(path)[0]
    plot_histogram(groups, base + '_relay_histogram.png')
    plot_scatter(groups,   base + '_relay_scatter.png')
    plot_relay_map(records, base + '_relay_map.png')

    json_path = base + '_relay_stats.json'
    with open(json_path, 'w') as f:
        json.dump(stats, f, indent=2)
    print(f"[INFO] Estatísticas JSON: {json_path}")


if __name__ == '__main__':
    main()
