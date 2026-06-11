#!/usr/bin/env python3
"""
tdma_sync_plot.py — Visualização de sincronização TDMA wrapped a 150ms

Uso:
  1. Capturar no Wireshark: filtro  udp portrange 7001-7003
  2. Exportar: File → Export Packet Dissections → As CSV
  3. python3 tdma_sync_plot.py <ficheiro.csv>

Produz dois plots (como Ana Morais Fig. 4.34/4.35):
  - Scatter: posição de cada pacote dentro do frame de 150ms
  - Histograma: distribuição por bin de 1ms dentro do frame
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
NODE_LABELS = {1: 'N1 (slot 0–50ms)', 2: 'N2 (slot 50–100ms)', 3: 'N3 (slot 100–150ms)'}
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
    ax.set_xlabel('Posição dentro do frame TDMA (ms)', fontsize=11)
    ax.set_ylabel('Nó emissor', fontsize=11)
    ax.set_title('Sincronização TDMA — posição de transmissão no frame de 150ms', fontsize=12)
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

        ax.set_ylabel(f'N{node}\n(pkts)', fontsize=9)
        ax.legend(loc='upper right', fontsize=8)
        ax.grid(axis='x', alpha=0.3)

        if positions:
            mean_pos = np.mean(positions)
            ax.axvline(x=mean_pos, color='orange', linewidth=1.5,
                       linestyle='-', alpha=0.9, label=f'μ={mean_pos:.1f}ms')

    axes[-1].set_xlabel('Posição dentro do frame TDMA (ms)', fontsize=11)
    axes[0].set_title('Distribuição de transmissões por slot (histograma 1ms)', fontsize=12)

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

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("Uso: python3 tdma_sync_plot.py <ficheiro.csv|ficheiro.pcap>")
        sys.exit(1)

    path = sys.argv[1]
    if not os.path.exists(path):
        print(f"ERRO: ficheiro não encontrado: {path}")
        sys.exit(1)

    # Carrega pacotes
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.pcap', '.pcapng'):
        print(f"[INFO] A ler pcap: {path}")
        packets = load_pcap_scapy(path)
    else:
        print(f"[INFO] A ler CSV Wireshark: {path}")
        packets = load_wireshark_csv(path)

    if not packets:
        print("ERRO: nenhum pacote UDP 7001-7003 encontrado no ficheiro.")
        print("Verifique que capturou com filtro: udp portrange 7001-7003")
        sys.exit(1)

    print(f"[INFO] {len(packets)} pacotes carregados ({len(set(n for _,n in packets))} nós)")

    # Wrap a 150ms
    wrapped = wrap_to_frame(packets)

    # Estatísticas
    stats = print_stats(wrapped)

    # Plots
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
