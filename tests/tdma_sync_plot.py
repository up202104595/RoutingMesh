#!/usr/bin/env python3
"""
tdma_sync_plot.py — Visualização de sincronização TDMA + análise de protocolo

Modos:
  1. Sincronização TDMA (beacons 7001-7003):
       python3 tdma_sync_plot.py <ficheiro.csv>

  2. Análise de protocolo directo vs relay (captura wlan0 completa):
       python3 tdma_sync_plot.py --proto <ficheiro.csv>
       python3 tdma_sync_plot.py --proto direct.csv relay.csv

     Mostra: em directo N3 recebe TCP (TDMA encapsulado);
             em relay   N3 recebe UDP/MPEG TS (ip_forward raw de N2)

Como capturar:
  - Beacons TDMA:  filtro Wireshark  udp portrange 7001-7003
  - Protocolo:     capturar wlan0 SEM filtro → exportar CSV completo
"""

import sys
import csv
import os
import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from collections import defaultdict

# ── Configuração TDMA ──────────────────────────────────────────────────────────
FRAME_MS   = 150.0   # duração do frame completo (ms)
SLOT_MS    = 50.0    # duração de cada slot (ms)
NUM_NODES  = 3

# Mapeamento porto → nó
# N1 TX na slot 0 → envia para porto 7002, 7003
# N2 TX na slot 1 → envia para porto 7001, 7003
# N3 TX na slot 2 → envia para porto 7001, 7002
#
# Para identificar o EMISSOR a partir do porto de DESTINO:
#   destport 7001 → pacote destinado a N1 → emitido por N2 ou N3
#   destport 7002 → destinado a N2 → emitido por N1 ou N3
#   destport 7003 → destinado a N3 → emitido por N1 ou N2
#
# Mas a forma mais fiável é pelo porto de ORIGEM (source port):
#   srcport 7001 → N1 está a emitir (slot 0, 0-50ms)
#   srcport 7002 → N2 está a emitir (slot 1, 50-100ms)
#   srcport 7003 → N3 está a emitir (slot 2, 100-150ms)
#
# O Wireshark captura tráfego bidirecional, portanto usamos srcport.

NODE_COLORS = {1: '#2196F3', 2: '#4CAF50', 3: '#F44336'}
NODE_LABELS = {1: 'N1 (slot 0–50 ms)', 2: 'N2 (slot 50–100 ms)', 3: 'N3 (slot 100–150 ms)'}
SLOT_START  = {1: 0.0, 2: 50.0, 3: 100.0}

# ── Leitura CSV do Wireshark ───────────────────────────────────────────────────
def load_wireshark_csv(path):
    """
    Lê CSV exportado pelo Wireshark.
    Colunas esperadas: No., Time, Source, Destination, Protocol, Length, Info
    Identifica o nó pelo IP de origem:
      172.20.10.1 = N1 (slot 0)
      172.20.10.2 = N2 (slot 1)
      172.20.10.3 = N3 (slot 2)
    Filtra apenas pacotes do protocolo RX (TDMA custom) com length 107.
    """
    import re
    packets = []

    IP_TO_NODE = {
        '172.20.10.1': 1,
        '172.20.10.2': 2,
        '172.20.10.3': 3,
    }

    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames
        if headers is None:
            print("ERRO: CSV vazio ou mal formatado")
            sys.exit(1)

        norm = {h.strip().lower(): h for h in headers}

        time_col   = norm.get('time')
        src_col    = norm.get('source')
        proto_col  = norm.get('protocol')
        len_col    = norm.get('length')

        if not time_col or not src_col:
            print("ERRO: colunas Time/Source não encontradas")
            print("Colunas disponíveis:", list(norm.keys()))
            sys.exit(1)

        for row in reader:
            try:
                ts  = float(row[time_col].strip())
                src = row[src_col].strip()

                # Filtra só pacotes RX (TDMA) — ignora MDNS, SSDP, etc.
                if proto_col:
                    proto = row[proto_col].strip().upper()
                    if proto not in ('RX', 'UDP'):
                        continue

                # Filtra por length 107 (tamanho fixo dos beacons TDMA)
                if len_col:
                    try:
                        pkt_len = int(row[len_col].strip())
                        if pkt_len != 107:
                            continue
                    except ValueError:
                        pass

                node = IP_TO_NODE.get(src)
                if node is None:
                    continue

                packets.append((ts, node))

            except (ValueError, KeyError):
                continue

    return packets

# ── Alternativa: captura ao vivo via scapy ────────────────────────────────────
def load_pcap_scapy(path):
    """Lê ficheiro .pcap directamente com scapy (alternativa ao CSV)."""
    try:
        from scapy.all import rdpcap, UDP
    except ImportError:
        print("scapy não instalado. Use CSV do Wireshark ou: pip3 install scapy")
        sys.exit(1)

    packets = []
    pkts = rdpcap(path)
    t0 = None
    for pkt in pkts:
        if UDP not in pkt:
            continue
        sport = pkt[UDP].sport
        if sport not in (7001, 7002, 7003):
            continue
        ts = float(pkt.time)
        if t0 is None:
            t0 = ts
        node = sport - 7000
        packets.append((ts - t0, node))
    return packets

# ── Processamento: wrap a 150ms ───────────────────────────────────────────────
def wrap_to_frame(packets):
    """
    Devolve dict {node: [pos_ms, ...]} onde pos_ms = timestamp_ms mod 150.
    """
    result = defaultdict(list)
    if not packets:
        return result

    t0 = packets[0][0]
    for (ts, node) in packets:
        ts_ms = (ts - t0) * 1000.0
        pos   = ts_ms % FRAME_MS
        result[node].append(pos)
    return result

# ── Plot 1: Scatter (como Fig. 4.34 da Ana) ──────────────────────────────────
def plot_scatter(wrapped, out_path):
    fig, ax = plt.subplots(figsize=(10, 4))

    for node, positions in sorted(wrapped.items()):
        # Usa os últimos 300 pacotes para não saturar o gráfico
        pos = positions[-300:]
        ax.scatter(pos, [node] * len(pos),
                   s=4, alpha=0.5, color=NODE_COLORS[node],
                   label=NODE_LABELS[node])

    # Linhas de fronteira de slot
    for boundary in [0, 50, 100, 150]:
        ax.axvline(x=boundary, color='black', linewidth=1.2,
                   linestyle='--', alpha=0.7)

    # Zonas coloridas por slot
    ax.axvspan(0,   50,  alpha=0.04, color=NODE_COLORS[1])
    ax.axvspan(50,  100, alpha=0.04, color=NODE_COLORS[2])
    ax.axvspan(100, 150, alpha=0.04, color=NODE_COLORS[3])

    ax.set_xlim(0, FRAME_MS)
    ax.set_ylim(0.5, NUM_NODES + 0.5)
    ax.set_yticks([1, 2, 3])
    ax.set_yticklabels(['N1', 'N2', 'N3'])
    ax.set_xlabel('Position within TDMA frame (ms)', fontsize=11)
    ax.set_ylabel('Transmitting node', fontsize=11)
    ax.set_title('TDMA Synchronization — transmission position within 150 ms frame', fontsize=12)
    ax.legend(loc='upper right', fontsize=9)
    ax.grid(axis='x', alpha=0.3)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"[PLOT] Scatter guardado: {out_path}")

# ── Plot 2: Histograma por nó (como Fig. 4.35 da Ana) ────────────────────────
def plot_histogram(wrapped, out_path):
    bins = np.arange(0, FRAME_MS + 1, 1)  # bins de 1ms

    fig, axes = plt.subplots(NUM_NODES, 1, figsize=(10, 7), sharex=True)

    for i, node in enumerate([1, 2, 3]):
        ax = axes[i]
        positions = wrapped.get(node, [])
        if positions:
            ax.hist(positions, bins=bins, color=NODE_COLORS[node],
                    alpha=0.8, edgecolor='none')
        # Fronteiras de slot
        for boundary in [0, 50, 100, 150]:
            ax.axvline(x=boundary, color='black', linewidth=1.0,
                       linestyle='--', alpha=0.7)
        # Zona do slot correcto
        slot_s = SLOT_START[node]
        ax.axvspan(slot_s, slot_s + SLOT_MS, alpha=0.12,
                   color=NODE_COLORS[node], label=f'Slot N{node}')

        ax.set_ylabel(f'N{node}\n(packets)', fontsize=9)
        ax.legend(loc='upper right', fontsize=8)
        ax.grid(axis='x', alpha=0.3)

        if positions:
            mean_pos = np.mean(positions)
            ax.axvline(x=mean_pos, color='orange', linewidth=1.5,
                       linestyle='-', alpha=0.9, label=f'mean = {mean_pos:.1f} ms')

    axes[-1].set_xlabel('Position within TDMA frame (ms)', fontsize=11)
    axes[0].set_title('Transmission distribution per slot (1 ms histogram)', fontsize=12)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"[PLOT] Histograma guardado: {out_path}")

# ── Estatísticas por nó ───────────────────────────────────────────────────────
def print_stats(wrapped):
    print("\n─── Estatísticas de sincronização TDMA ───────────────────────────")
    print(f"{'Nó':>4}  {'Slot esperado':>14}  {'N pkts':>7}  {'μ (ms)':>8}  "
          f"{'σ (ms)':>8}  {'% dentro slot':>14}")
    print("─" * 68)
    results = {}
    for node in [1, 2, 3]:
        positions = wrapped.get(node, [])
        if not positions:
            print(f"   N{node}   —  sem dados")
            continue
        arr = np.array(positions)
        mu  = np.mean(arr)
        sig = np.std(arr)
        sl_s = SLOT_START[node]
        sl_e = sl_s + SLOT_MS
        inside = np.sum((arr >= sl_s) & (arr < sl_e))
        pct = 100.0 * inside / len(arr)
        print(f"   N{node}   {sl_s:.0f}–{sl_e:.0f} ms      {len(arr):>7}  {mu:>8.2f}  "
              f"{sig:>8.2f}  {pct:>13.1f}%")
        results[f'N{node}'] = {'n': len(arr), 'mean_ms': round(mu,2),
                                'std_ms': round(sig,2), 'pct_in_slot': round(pct,1)}
    print("─" * 68)
    return results

# ── Análise de protocolo: TCP (directo) vs UDP/MPEG TS (relay) ────────────────
def _load_full_csv(path):
    """Lê CSV Wireshark SEM filtro — devolve lista de dicts com todos os campos."""
    rows = []
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        norm = {h.strip().strip('"').lower(): h for h in (reader.fieldnames or [])}
        tc = norm.get('time'); sc = norm.get('source'); dc = norm.get('destination')
        pc = norm.get('protocol'); lc = norm.get('length'); ic = norm.get('info')
        if not tc or not sc:
            print(f"ERRO: CSV sem colunas Time/Source: {path}"); sys.exit(1)
        t0 = None
        for row in reader:
            try:
                ts    = float(row[tc].strip().strip('"'))
                src   = row[sc].strip().strip('"')
                dst   = row[dc].strip().strip('"') if dc else ''
                proto = row[pc].strip().strip('"').upper() if pc else ''
                plen  = int(row[lc].strip().strip('"')) if lc else 0
            except (ValueError, KeyError):
                continue
            if t0 is None:
                t0 = ts
            rows.append({'ts_ms': (ts-t0)*1000, 'src': src, 'dst': dst,
                         'proto': proto, 'plen': plen})
    return rows


def _classify_proto(row):
    """
    Classifica o tipo de pacote relevante para a análise de relay.
    Retorna uma string legível ou None para ignorar.
    """
    src, dst, proto, plen = row['src'], row['dst'], row['proto'], row['plen']

    # Beacons TDMA de controlo (RX protocol, 172.20.x.x)
    if proto == 'RX' and plen <= 120:
        return 'TDMA Beacon\n(RX ctrl)'

    # Dados vídeo encapsulados em TCP TDMA — porta 8001-8003
    if proto == 'TCP' and src.startswith('172.20.') and dst.startswith('172.20.'):
        return 'TCP TDMA\n(encapsulated video)'

    # Vídeo raw via ip_forward — porta 5000 UDP/MPEG TS
    if proto in ('UDP', 'MPEG TS') and plen > 200:
        return 'UDP / MPEG TS\n(ip_forward raw)'

    return None


def _proto_analysis(files):
    """
    Analisa 1 ou 2 CSVs e mostra distribuição de protocolos.
    Com 2 ficheiros: compara directo vs relay lado a lado.
    """
    labels = ['Direct (N1→N3)', 'Relay (N1→N2→N3)'] if len(files) == 2 else [os.path.basename(files[0])]
    datasets = [_load_full_csv(f) for f in files]

    # conta por protocolo classificado
    def count_protos(rows):
        from collections import Counter
        c = Counter()
        for r in rows:
            k = _classify_proto(r)
            if k:
                c[k] += 1
        return c

    counts = [count_protos(d) for d in datasets]
    all_keys = sorted(set(k for c in counts for k in c))

    # imprime tabela
    print("\n─── Distribuição de protocolos ─────────────────────────────────────────")
    print(f"  {'Tipo de pacote':<32}", end='')
    for lbl in labels:
        print(f"  {lbl[:20]:>20}", end='')
    print()
    print("  " + "─" * (32 + 22 * len(labels)))
    for k in all_keys:
        print(f"  {k.replace(chr(10), ' '):<32}", end='')
        for c in counts:
            print(f"  {c.get(k, 0):>20}", end='')
        print()

    # gráfico
    fig, axes = plt.subplots(1, len(files), figsize=(6 * len(files), 5), squeeze=False)
    colors = ['#2196F3', '#FF9800', '#4CAF50', '#9C27B0']

    for col_i, (ax, c, lbl) in enumerate(zip(axes[0], counts, labels)):
        keys = all_keys
        vals = [c.get(k, 0) for k in keys]
        x    = np.arange(len(keys))
        bars = ax.bar(x, vals, color=colors[:len(keys)], alpha=0.85, edgecolor='white')

        # anotação do valor em cima de cada barra
        for bar, v in zip(bars, vals):
            if v > 0:
                ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + max(vals)*0.01,
                        str(v), ha='center', va='bottom', fontsize=9)

        ax.set_xticks(x)
        ax.set_xticklabels([k.replace('\n', '\n') for k in keys], fontsize=8)
        ax.set_ylabel('Number of packets')
        ax.set_title(lbl, fontsize=10, fontweight='bold')
        ax.grid(axis='y', alpha=0.3)

        # box explicativo
        if 'Relay' in lbl or col_i == 1:
            ax.text(0.5, 0.92,
                    'UDP/MPEG TS = ip_forward\nbypasses TDMA encapsulation',
                    transform=ax.transAxes, ha='center', fontsize=7,
                    color='#4CAF50',
                    bbox=dict(boxstyle='round', facecolor='#E8F5E9', alpha=0.8))
        else:
            ax.text(0.5, 0.92,
                    'TCP = video encapsulated\nin TDMA protocol',
                    transform=ax.transAxes, ha='center', fontsize=7,
                    color='#2196F3',
                    bbox=dict(boxstyle='round', facecolor='#E3F2FD', alpha=0.8))

    fig.suptitle('Protocol received at N3: Direct vs. Relay\n'
                 'In relay the protocol changes from TCP (TDMA) to UDP/MPEG TS (ip_forward)',
                 fontsize=10, fontweight='bold')
    plt.tight_layout()

    base  = os.path.splitext(files[0])[0]
    opath = base + '_proto_comparison.png'
    plt.savefig(opath, dpi=150)
    plt.close()
    print(f"\n[PLOT] {opath}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('files', nargs='+',
                        help='CSV(s) Wireshark — 1 ficheiro (sync) ou 2 (direct relay)')
    parser.add_argument('--proto', action='store_true',
                        help='Modo análise de protocolo TCP vs MPEG TS (directo vs relay)')
    args = parser.parse_args()

    for f in args.files:
        if not os.path.exists(f):
            print(f"ERRO: ficheiro não encontrado: {f}"); sys.exit(1)

    if args.proto:
        # ── Modo protocolo ──────────────────────────────────────────────────
        _proto_analysis(args.files)
        return

    # ── Modo sincronização (comportamento original) ─────────────────────────
    path = args.files[0]
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.pcap', '.pcapng'):
        print(f"[INFO] A ler pcap: {path}")
        packets = load_pcap_scapy(path)
    else:
        print(f"[INFO] A ler CSV Wireshark: {path}")
        packets = load_wireshark_csv(path)

    if not packets:
        print("ERRO: nenhum pacote beacon TDMA encontrado.")
        print("  Para beacons: capturar com filtro  udp portrange 7001-7003")
        print("  Para protocolo: usar flag --proto")
        sys.exit(1)

    print(f"[INFO] {len(packets)} pacotes carregados ({len(set(n for _,n in packets))} nós)")

    wrapped = wrap_to_frame(packets)
    stats   = print_stats(wrapped)

    base = os.path.splitext(path)[0]
    plot_scatter   (wrapped, base + '_scatter.png')
    plot_histogram (wrapped, base + '_histogram.png')

    # Guarda JSON com estatísticas
    json_path = base + '_stats.json'
    with open(json_path, 'w') as f:
        json.dump(stats, f, indent=2)
    print(f"[INFO] Estatísticas JSON: {json_path}")

if __name__ == '__main__':
    main()
