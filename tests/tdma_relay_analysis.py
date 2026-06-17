#!/usr/bin/env python3
"""
tdma_relay_analysis.py — Análise de timing do relay TDMA

Analisa QUANDO os pacotes de vídeo são transmitidos/recebidos
em relação ao frame TDMA de 150ms.

O relay é transparente ao IP (o kernel faz ip-forward via TUN),
por isso os pacotes chegam sempre com src=nó_origem. A prova do
relay está no TIMING: pacotes chegando no slot de N2 (50-100ms)
foram re-transmitidos por N2.

Lê .pcap/.pcapng diretamente (sem dependências externas).
Suporta link types: Ethernet (1), Linux SLL (113), Linux SLL2 (276).

Uso:
  python3 tdma_relay_analysis.py <ficheiro.pcap>   [--port PORT]
  python3 tdma_relay_analysis.py <ficheiro.pcap>   --scan
  python3 tdma_relay_analysis.py <ficheiro.csv>

  --scan    mostra o que existe no pcap (diagnóstico)
  --port P  filtra por porto de destino (default: qualquer)
"""

import sys, os, csv, json, struct
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from collections import defaultdict

# ── Configuração TDMA ──────────────────────────────────────────────────────────
FRAME_MS        = 150.0
SLOT_MS         = 50.0
NUM_NODES       = 3
MIN_UDP_PAYLOAD = 100   # beacons têm ~65 B UDP payload; vídeo tem 1316 B

# IPs conhecidos → nó
IP_TO_NODE = {
    '172.20.10.1': 1, '172.20.10.2': 2, '172.20.10.3': 3,
    '10.0.0.1':    1, '10.0.0.2':    2, '10.0.0.3':    3,
}
NODE_COLORS = {1: '#2196F3', 2: '#4CAF50', 3: '#F44336'}
NODE_NAMES  = {1: 'N1', 2: 'N2', 3: 'N3'}
SLOT_START  = {1: 0.0, 2: 50.0, 3: 100.0}
TDMA_PORTS  = {7001, 7002, 7003}


def infer_relay_node(frame_pos):
    """Devolve o nó relay inferido pela posição no frame TDMA (ou 0 se ambíguo)."""
    for node, start in SLOT_START.items():
        if start <= frame_pos < start + SLOT_MS:
            return node
    return 0


# ── Stripping L2 ───────────────────────────────────────────────────────────────
def _strip_l2(data, link_type):
    """Remove cabeçalho L2 e devolve bytes IP (IPv4) ou None."""
    if link_type == 1:      # Ethernet
        if len(data) < 14: return None
        if struct.unpack('>H', data[12:14])[0] != 0x0800: return None
        return data[14:]
    elif link_type == 113:  # Linux cooked v1 (SLL)
        if len(data) < 16: return None
        if struct.unpack('>H', data[14:16])[0] != 0x0800: return None
        return data[16:]
    elif link_type == 276:  # Linux cooked v2 (SLL2) — gerado por tcpdump -i any
        if len(data) < 20: return None
        if struct.unpack('>H', data[0:2])[0] != 0x0800: return None
        return data[20:]
    return None


# ── Iteradores pcap / pcapng ───────────────────────────────────────────────────
SUPPORTED_LINKTYPES = {1, 113, 276}

def _iter_classic_pcap(f):
    raw = f.read(4)
    if len(raw) < 4:
        return
    le = struct.unpack('<I', raw)[0]
    if le in (0xa1b2c3d4, 0xa1b23c4d):
        endian, ns = '<', (le == 0xa1b23c4d)
    else:
        be = struct.unpack('>I', raw)[0]
        if be in (0xa1b2c3d4, 0xa1b23c4d):
            endian, ns = '>', (be == 0xa1b23c4d)
        else:
            print("ERRO: não é um ficheiro pcap válido"); return
    gh = f.read(20)
    if len(gh) < 20:
        return
    network = struct.unpack(f'{endian}I', gh[16:20])[0]
    if network not in SUPPORTED_LINKTYPES:
        print(f"ERRO: link type {network} não suportado "
              f"(suportados: 1=Ethernet, 113=Linux SLL, 276=Linux SLL2)")
        return
    div = 1_000_000_000 if ns else 1_000_000
    while True:
        hdr = f.read(16)
        if len(hdr) < 16: break
        ts_sec, ts_frac, incl_len, _ = struct.unpack(f'{endian}IIII', hdr)
        data = f.read(incl_len)
        if len(data) < incl_len: break
        yield ts_sec + ts_frac / div, data, network


def _iter_pcapng(f):
    raw12 = f.read(12)
    if len(raw12) < 12 or struct.unpack('<I', raw12[0:4])[0] != 0x0A0D0D0A:
        return
    bom = struct.unpack('<I', raw12[8:12])[0]
    endian = '<' if bom == 0x1A2B3C4D else ('>' if bom == 0x4D3C2B1A else None)
    if not endian: return
    shb_len = struct.unpack(f'{endian}I', raw12[4:8])[0]
    f.seek(shb_len - 12, 1)
    ifaces = {}
    while True:
        hdr = f.read(8)
        if len(hdr) < 8: break
        btype, blen = struct.unpack(f'{endian}II', hdr)
        body = f.read(blen - 12)
        f.read(4)
        if btype == 0x00000001 and len(body) >= 2:
            ltype = struct.unpack(f'{endian}H', body[0:2])[0]
            ifaces[len(ifaces)] = (ltype, 1_000_000)
        elif btype == 0x00000006 and len(body) >= 20:
            iface_id = struct.unpack(f'{endian}I', body[0:4])[0]
            ts_hi = struct.unpack(f'{endian}I', body[4:8])[0]
            ts_lo = struct.unpack(f'{endian}I', body[8:12])[0]
            cap_len = struct.unpack(f'{endian}I', body[12:16])[0]
            ltype, div = ifaces.get(iface_id, (1, 1_000_000))
            yield ((ts_hi << 32) | ts_lo) / div, body[20:20 + cap_len], ltype


def _open_pcap(path):
    f = open(path, 'rb')
    magic = struct.unpack('<I', f.read(4))[0]
    f.seek(0)
    return (_iter_pcapng(f) if magic == 0x0A0D0D0A else _iter_classic_pcap(f)), f


def _udp_fields(ip_bytes):
    """Devolve (ip_src, sport, dport, udp_payload_len) ou None. Só IPv4/UDP."""
    if len(ip_bytes) < 20:
        return None
    ip_ihl = (ip_bytes[0] & 0x0F) * 4
    if ip_bytes[9] != 17:   # UDP
        return None
    ip_src = f'{ip_bytes[12]}.{ip_bytes[13]}.{ip_bytes[14]}.{ip_bytes[15]}'
    udp_off = ip_ihl
    if len(ip_bytes) < udp_off + 8:
        return None
    sport, dport = struct.unpack('>HH', ip_bytes[udp_off:udp_off + 4])
    udp_len = struct.unpack('>H', ip_bytes[udp_off + 4:udp_off + 6])[0]
    return ip_src, sport, dport, max(0, udp_len - 8)


# ── Scan diagnóstico ──────────────────────────────────────────────────────────
def scan_pcap(path):
    print(f"\n[SCAN] {path}\n")
    stats = defaultdict(lambda: {'n': 0, 'min': 9999, 'max': 0})

    pkt_iter, f = _open_pcap(path)
    with f:
        for _, frame, ltype in pkt_iter:
            ip_bytes = _strip_l2(frame, ltype)
            if ip_bytes is None: continue
            r = _udp_fields(ip_bytes)
            if not r: continue
            ip_src, sport, dport, plen = r
            key = (ip_src, f'{sport}→{dport}')
            stats[key]['n'] += 1
            stats[key]['min'] = min(stats[key]['min'], plen)
            stats[key]['max'] = max(stats[key]['max'], plen)

    print(f"  {'IP origem':>16}  {'Portos UDP':>16}  {'Pkts':>6}  {'UDP payload (B)':>18}  Nó")
    print("  " + "─" * 70)
    for (src, ports), info in sorted(stats.items(), key=lambda x: -x[1]['n']):
        node = IP_TO_NODE.get(src, '?')
        beacon = ' ← beacons' if info['max'] < MIN_UDP_PAYLOAD else ''
        print(f"  {src:>16}  {ports:>16}  {info['n']:>6}"
              f"  {info['min']}–{info['max']} B  N{node}{beacon}")
    print()


# ── Carregamento pcap ─────────────────────────────────────────────────────────
def load_pcap(path, video_port=None):
    print(f"[INFO] A ler: {path}")
    records = []
    t0 = None
    n_skip_beacon = 0
    n_skip_ip = 0

    pkt_iter, f = _open_pcap(path)
    with f:
        for ts, frame, ltype in pkt_iter:
            ip_bytes = _strip_l2(frame, ltype)
            if ip_bytes is None:
                continue
            r = _udp_fields(ip_bytes)
            if not r:
                continue
            ip_src, sport, dport, plen = r

            if sport in TDMA_PORTS or dport in TDMA_PORTS:
                n_skip_beacon += 1
                continue

            if plen < MIN_UDP_PAYLOAD:
                n_skip_beacon += 1
                continue

            if video_port is not None and dport != video_port:
                continue

            node = IP_TO_NODE.get(ip_src, 0)
            if node == 0:
                n_skip_ip += 1
                continue

            if t0 is None:
                t0 = ts
            ts_ms = (ts - t0) * 1000.0

            records.append({
                'ts_ms':     ts_ms,
                'frame_pos': ts_ms % FRAME_MS,
                'node':      node,
                'ip_src':    ip_src,
                'dport':     dport,
                'plen':      plen,
            })

    print(f"[INFO] {len(records)} pacotes de vídeo carregados"
          + (f"  (porta {video_port})" if video_port else ""))
    if n_skip_beacon:
        print(f"[INFO] {n_skip_beacon} beacons/pequenos ignorados")
    if n_skip_ip:
        print(f"[WARN] {n_skip_ip} pacotes de IPs desconhecidos ignorados")

    return records


# ── Carregamento CSV ──────────────────────────────────────────────────────────
def load_csv(path):
    """
    Carrega pacotes do CSV exportado pelo Wireshark.

    Estratégia de dois planos:
      - Plano de dados  (10.0.0.x / MPEG TS / UDP): só pacotes de vídeo (len > 107).
        O src IP permanece o do originador mesmo após relay transparente via TUN.
        O relay de N2 é INFERIDO pela posição no frame TDMA (slot 50-100ms).
      - Plano de controlo (172.20.10.x / RX): beacons TDMA — mostram quando cada
        nó está activo no seu slot, incluindo N2 que não aparece como src de vídeo.
    """
    print(f"[INFO] A ler CSV: {path}")
    records  = []
    t0       = None
    n_video  = 0
    n_beacon = 0
    skip     = 0

    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        norm = {h.strip().lower(): h for h in (reader.fieldnames or [])}
        tc = norm.get('time'); sc = norm.get('source')
        lc = norm.get('length'); pc = norm.get('protocol')
        dc = norm.get('destination')
        if not tc or not sc:
            print("ERRO: colunas Time/Source não encontradas"); sys.exit(1)

        for row in reader:
            try:
                ts  = float(row[tc].strip())
                src = row[sc].strip()
            except (ValueError, KeyError):
                continue

            proto = row[pc].strip().upper() if pc else ''
            try:
                plen = int(row[lc].strip()) if lc else 0
            except ValueError:
                plen = 0

            node = IP_TO_NODE.get(src, 0)
            if node == 0:
                skip += 1; continue

            is_ctrl_plane = src.startswith('172.20.')

            if is_ctrl_plane:
                # Beacons RX do plano de controlo TDMA — mostram actividade do slot
                if proto != 'RX':
                    skip += 1; continue
                pkt_type = 'beacon'
                n_beacon += 1
            else:
                # Plano de dados — só vídeo (filtra beacons pequenos)
                if proto not in ('UDP', 'MPEG TS'):
                    skip += 1; continue
                if plen <= 107:
                    skip += 1; continue
                pkt_type = 'video'
                n_video += 1

            if t0 is None:
                t0 = ts
            ts_ms     = (ts - t0) * 1000.0
            frame_pos = ts_ms % FRAME_MS

            records.append({
                'ts_ms':      ts_ms,
                'frame_pos':  frame_pos,
                'node':       node,
                'ip_src':     src,
                'ip_dst':     row[dc].strip() if dc else '',
                'plen':       plen,
                'pkt_type':   pkt_type,
                'relay_node': infer_relay_node(frame_pos) if pkt_type == 'video' else node,
            })

    print(f"[INFO] {n_video} pacotes de vídeo + {n_beacon} beacons carregados ({skip} ignorados)")
    return records


# ── Estatísticas ───────────────────────────────────────────────────────────────
def compute_stats(records):
    # Separa vídeo de beacons
    by_node_video   = defaultdict(list)  # frame_pos dos pacotes de vídeo (por src node)
    by_node_beacon  = defaultdict(list)  # frame_pos dos beacons de controlo
    by_relay_node   = defaultdict(list)  # frame_pos dos pacotes de vídeo por relay inferido

    for r in records:
        if r['pkt_type'] == 'video':
            by_node_video[r['node']].append(r['frame_pos'])
            if r['relay_node']:
                by_relay_node[r['relay_node']].append(r['frame_pos'])
        else:
            by_node_beacon[r['node']].append(r['frame_pos'])

    print("\n─── Timing do vídeo relay no frame TDMA ──────────────────────────────────")
    print(f"  {'Nó src':>6}  {'IP origem':>16}  {'N pkts':>7}  "
          f"{'μ (ms)':>8}  {'σ (ms)':>7}  {'% no slot':>10}")
    print("  " + "─" * 62)

    ip_by_node = defaultdict(set)
    for r in records:
        if r['pkt_type'] == 'video':
            ip_by_node[r['node']].add(r['ip_src'])

    results = {}
    all_video_nodes = sorted(set(by_node_video) | set(by_relay_node))
    for node in all_video_nodes:
        pos  = np.array(by_node_video.get(node, []))
        if len(pos) == 0:
            continue
        mu   = np.mean(pos)
        sig  = np.std(pos)
        sl_s = SLOT_START.get(node, -1)
        pct  = 100.0 * np.sum((pos >= sl_s) & (pos < sl_s + SLOT_MS)) / len(pos) \
               if sl_s >= 0 else 0.0
        ips  = ', '.join(sorted(ip_by_node[node]))
        print(f"  N{node}      {ips:>16}  {len(pos):>7}  "
              f"{mu:>8.2f}  {sig:>7.2f}  {pct:>9.1f}%")
        results[f'N{node}_video'] = {'n': len(pos), 'mean_ms': round(mu, 2),
                                      'std_ms': round(sig, 2), 'pct_in_slot': round(pct, 1)}

    print("\n─── Relay inferido por slot TDMA (vídeo recebido em cada slot) ───────────")
    print(f"  {'Slot/Nó':>7}  {'N pkts':>7}  {'μ (ms)':>8}  {'σ (ms)':>7}  {'Intervalo slot':>16}")
    print("  " + "─" * 55)
    for node in sorted(by_relay_node):
        pos  = np.array(by_relay_node[node])
        mu   = np.mean(pos)
        sig  = np.std(pos)
        sl_s = SLOT_START[node]
        print(f"  N{node} slot  {len(pos):>7}  {mu:>8.2f}  {sig:>7.2f}  "
              f"  {sl_s:.0f}–{sl_s+SLOT_MS:.0f} ms")
        results[f'N{node}_relay_slot'] = {'n': len(pos), 'mean_ms': round(mu, 2),
                                           'std_ms': round(sig, 2)}

    print("\n─── Actividade beacons TDMA (plano de controlo 172.20.x.x) ──────────────")
    print(f"  {'Nó':>4}  {'N beacons':>9}  {'μ (ms)':>8}  {'σ (ms)':>7}  {'% no slot':>10}")
    print("  " + "─" * 50)
    for node in sorted(by_node_beacon):
        pos  = np.array(by_node_beacon[node])
        mu   = np.mean(pos)
        sig  = np.std(pos)
        sl_s = SLOT_START.get(node, -1)
        pct  = 100.0 * np.sum((pos >= sl_s) & (pos < sl_s + SLOT_MS)) / len(pos) \
               if sl_s >= 0 else 0.0
        print(f"  N{node}    {len(pos):>9}  {mu:>8.2f}  {sig:>7.2f}  {pct:>9.1f}%")
        results[f'N{node}_beacon'] = {'n': len(pos), 'mean_ms': round(mu, 2),
                                       'std_ms': round(sig, 2), 'pct_in_slot': round(pct, 1)}
    print("  " + "─" * 50)

    return results, by_node_video, by_node_beacon, by_relay_node


# ── Plot histograma ────────────────────────────────────────────────────────────
def plot_histogram(by_node, out_path):
    bins = np.arange(0, FRAME_MS + 1, 1)
    active = [n for n in [1, 2, 3] if n in by_node]
    fig, axes = plt.subplots(len(active), 1,
                             figsize=(12, 3 * len(active) + 1), sharex=True)
    if len(active) == 1:
        axes = [axes]
    fig.suptitle('Timing do vídeo relay no frame TDMA de 150ms', fontsize=12, fontweight='bold')

    for i, node in enumerate(active):
        ax  = axes[i]
        pos = by_node[node]
        col = NODE_COLORS[node]
        ax.hist(pos, bins=bins, color=col, alpha=0.8, edgecolor='none')
        mu = np.mean(pos)
        ax.axvline(x=mu, color='orange', lw=1.8,
                   label=f'μ={mu:.1f}ms  σ={np.std(pos):.1f}ms  n={len(pos)}')
        sl_s = SLOT_START[node]
        for b in [0, 50, 100, 150]:
            ax.axvline(x=b, color='black', lw=0.9, linestyle='--', alpha=0.6)
        ax.axvspan(sl_s, sl_s + SLOT_MS, alpha=0.14, color=col,
                   label=f'Slot esperado N{node} ({sl_s:.0f}–{sl_s+SLOT_MS:.0f} ms)')
        ax.set_ylabel(f'N{node}\n(pkts)', fontsize=9)
        ax.legend(loc='upper right', fontsize=8)
        ax.grid(axis='x', alpha=0.3)

    axes[-1].set_xlabel('Posição dentro do frame TDMA (ms)', fontsize=11)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"[PLOT] {out_path}")


# ── Plot scatter ───────────────────────────────────────────────────────────────
def plot_scatter(by_node, out_path):
    fig, ax = plt.subplots(figsize=(12, 3))
    ax.set_title('Timing do vídeo relay — scatter por nó (source IP)', fontsize=11)

    for node, positions in sorted(by_node.items()):
        pos = positions[-600:] if len(positions) > 600 else positions
        ax.scatter(pos, [node] * len(pos), s=5, alpha=0.4,
                   color=NODE_COLORS.get(node, '#888'), label=f'N{node}')

    for b in [0, 50, 100, 150]:
        ax.axvline(x=b, color='black', lw=1.0, linestyle='--', alpha=0.65)
    ax.axvspan(0,   50,  alpha=0.06, color=NODE_COLORS[1])
    ax.axvspan(50,  100, alpha=0.06, color=NODE_COLORS[2])
    ax.axvspan(100, 150, alpha=0.06, color=NODE_COLORS[3])
    ax.set_xlim(0, FRAME_MS)
    active = sorted(by_node.keys())
    ax.set_ylim(min(active) - 0.5, max(active) + 0.5)
    ax.set_yticks(active)
    ax.set_yticklabels([f'N{n}' for n in active])
    ax.set_xlabel('Posição dentro do frame TDMA (ms)', fontsize=11)
    ax.legend(loc='upper right', fontsize=9)
    ax.grid(axis='x', alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"[PLOT] {out_path}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)

    path = sys.argv[1]
    if not os.path.exists(path):
        print(f"ERRO: ficheiro não encontrado: {path}"); sys.exit(1)

    if '--scan' in sys.argv:
        scan_pcap(path)
        return

    video_port = None
    if '--port' in sys.argv:
        idx = sys.argv.index('--port')
        if idx + 1 < len(sys.argv):
            video_port = int(sys.argv[idx + 1])

    ext = os.path.splitext(path)[1].lower()
    if ext in ('.pcap', '.pcapng'):
        records = load_pcap(path, video_port)
    else:
        records = load_csv(path)

    if not records:
        print("\nNenhum pacote de vídeo encontrado.")
        print("A correr diagnóstico automático...\n")
        if ext in ('.pcap', '.pcapng'):
            scan_pcap(path)
            print("→ Usa --port <N> para filtrar por porto de destino do vídeo.")
        sys.exit(1)

    stats, by_node = compute_stats(records)

    base = os.path.splitext(path)[0]
    plot_histogram(by_node, base + '_relay_histogram.png')
    plot_scatter(by_node,   base + '_relay_scatter.png')

    with open(base + '_relay_stats.json', 'w') as jf:
        json.dump(stats, jf, indent=2)
    print(f"[INFO] JSON: {base}_relay_stats.json")


if __name__ == '__main__':
    main()
