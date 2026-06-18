#!/usr/bin/env python3
"""
tdma_relay_analysis.py — Análise de relay TDMA a partir de CSVs Wireshark

Modos de uso:

  1) Análise em N3 — prova que relay muda protocolo e src:
       python3 tdma_relay_analysis.py --n3 direct.csv relay.csv

  2) Análise em N2 — mede a latência do relay (tempo receber → libertar):
       python3 tdma_relay_analysis.py --n2 n2_relay.csv
       Produz um único gráfico: histograma + CDF do Δt do ip_forward.

  3) Análise completa (N2 + N3):
       python3 tdma_relay_analysis.py --n2 n2_relay.csv --n3 direct.csv relay.csv

O CSV deve ser exportado do Wireshark com:
  File → Export Packet Dissections → As CSV
  Colunas: No., Time, Source, Destination, Protocol, Length, Info

Porquê o protocolo muda em N3?
  - Directo:  N1 envia via TDMA TCP (172.20.10.1 → 172.20.10.3  TCP  porta 8003)
  - Relay:    N2 faz ip_forward do pacote original — o relay é TRANSPARENTE
              (sem NAT), por isso o pacote mantém os IPs TUN originais
              (10.0.0.1 → 10.0.0.3) e aparece como MPEG TS porta 5000.
  O ip_forward bypassa o encapsulamento TDMA — o pacote raw MPEG TS vai directo
  para wlan0, sem passar pelo tx_queue nem pelo tx_loop do protocolo.

O que medir em N2 (capturar em N2 durante relay):
  - ENTRADA: 172.20.10.1 → 172.20.10.2  TCP  porta 800x  (vídeo encapsulado TDMA)
  - SAÍDA:   10.0.0.1 → 10.0.0.3  MPEG TS/UDP  porta 5000  (ip_forward transparente)
             NOTA: como o relay NÃO faz NAT, o src continua a ser 10.0.0.1 (N1),
             e NÃO 172.20.10.2 (N2). O pacote é reencaminhado tal e qual.
  - Δt = t_saída_MPEGTS − t_entrada_TCP  → latência do ip_forward kernel (~0ms)
"""

import sys, os, csv, argparse
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from collections import defaultdict

# ── Configuração ──────────────────────────────────────────────────────────────
FRAME_MS   = 150.0
SLOT_MS    = 50.0

IP_PHYS = {'172.20.10.1': 1, '172.20.10.2': 2, '172.20.10.3': 3}
IP_TUN  = {'10.0.0.1': 1, '10.0.0.2': 2, '10.0.0.3': 3}

NODE_COLOR = {1: '#2196F3', 2: '#4CAF50', 3: '#F44336'}

TDMA_TCP_PORTS  = {8001, 8002, 8003}   # portos TCP do protocolo TDMA
VIDEO_UDP_PORTS = {5000}               # porto vídeo MPEG TS
CTRL_UDP_PORTS  = {7001, 7002, 7003, 9001, 9002}  # beacons + feedback


# ── Leitura CSV ───────────────────────────────────────────────────────────────
def _port_from_info(info):
    """Extrai porto de destino do campo Info do Wireshark (heurística)."""
    import re
    m = re.search(r'>\s*(\d+)', info)
    return int(m.group(1)) if m else None


def load_csv(path):
    """
    Lê CSV Wireshark. Devolve lista de dicts com campos normalizados.
    Classifica cada pacote como: 'tdma_tcp', 'video_udp', 'ctrl', 'other'.
    """
    rows = []
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        norm = {h.strip().strip('"').lower(): h for h in (reader.fieldnames or [])}

        def col(name):
            return norm.get(name)

        tc = col('time'); sc = col('source'); dc = col('destination')
        pc = col('protocol'); lc = col('length'); ic = col('info')

        if not tc or not sc:
            print(f"ERRO: CSV sem colunas Time/Source: {path}")
            sys.exit(1)

        t0 = None
        for row in reader:
            try:
                ts  = float(row[tc].strip().strip('"'))
                src = row[sc].strip().strip('"')
                dst = row[dc].strip().strip('"') if dc else ''
                proto = row[pc].strip().strip('"').upper() if pc else ''
                info  = row[ic].strip().strip('"') if ic else ''
                try:
                    plen = int(row[lc].strip().strip('"')) if lc else 0
                except ValueError:
                    plen = 0
            except (ValueError, KeyError):
                continue

            if t0 is None:
                t0 = ts
            ts_ms = (ts - t0) * 1000.0

            # classificação
            dport = _port_from_info(info)
            # Porto de origem (src port) para TCP TDMA: "8001 > 51354"
            import re as _re
            sport_m = _re.search(r'(\d+)\s*>', info)
            sport = int(sport_m.group(1)) if sport_m else None

            if proto == 'TCP' and (sport in TDMA_TCP_PORTS or dport in TDMA_TCP_PORTS):
                ptype = 'tdma_tcp'
            elif proto == 'MPEG TS':
                ptype = 'video_udp'  # MPEG TS relay via ip_forward (TUN IPs)
            elif dport in CTRL_UDP_PORTS or proto == 'RX':
                ptype = 'ctrl'  # beacons/telemetria — verificar ANTES do vídeo UDP
            elif proto == 'UDP' and dport in VIDEO_UDP_PORTS:
                ptype = 'video_udp'
            else:
                ptype = 'other'

            src_node = IP_PHYS.get(src) or IP_TUN.get(src, 0)
            dst_node = IP_PHYS.get(dst) or IP_TUN.get(dst, 0)

            rows.append({
                'ts_ms':    ts_ms,
                'src':      src,
                'dst':      dst,
                'proto':    proto,
                'plen':     plen,
                'info':     info,
                'ptype':    ptype,
                'src_node': src_node,
                'dst_node': dst_node,
                'dport':    dport,
                'frame_pos': ts_ms % FRAME_MS,
            })

    print(f"[INFO] {path}: {len(rows)} pacotes")
    return rows


# ── Análise N3 — prova do relay ───────────────────────────────────────────────
def analyse_n3(direct_csv, relay_csv, out_prefix):
    """
    Compara capturas em N3: directo vs relay.
    Prova: em relay o src físico muda para N2 e o protocolo passa a UDP/MPEG TS.
    """
    direct = load_csv(direct_csv)
    relay  = load_csv(relay_csv)

    def classify_n3(rows):
        """Conta pacotes por (src_fisico, protocolo) que chegam a N3."""
        counts = defaultdict(int)
        for r in rows:
            if r['dst_node'] != 3 and r['dst'] not in ('10.0.0.3', '172.20.10.3'):
                continue
            key = (r['src'], r['proto'] if r['proto'] != 'MPEG TS' else 'UDP/MPEG TS')
            counts[key] += 1
        return counts

    d_counts = classify_n3(direct)
    r_counts = classify_n3(relay)

    print("\n─── N3: O que chega em modo DIRECTO ────────────────────────────────────")
    print(f"  {'Src IP':>16}  {'Protocolo':>12}  {'Pkts':>7}  Significado")
    for (src, proto), n in sorted(d_counts.items(), key=lambda x: -x[1]):
        sig = _significance(src, proto)
        print(f"  {src:>16}  {proto:>12}  {n:>7}  {sig}")

    print("\n─── N3: O que chega em modo RELAY ──────────────────────────────────────")
    print(f"  {'Src IP':>16}  {'Protocolo':>12}  {'Pkts':>7}  Significado")
    for (src, proto), n in sorted(r_counts.items(), key=lambda x: -x[1]):
        sig = _significance(src, proto)
        print(f"  {src:>16}  {proto:>12}  {n:>7}  {sig}")

    _print_category_breakdown(direct, 'DIRECTO')
    _print_category_breakdown(relay, 'RELAY')

    _plot_n3_slot_alignment(direct, relay, out_prefix + '_n3_slot_alignment.png')
    _plot_n3_performance(direct, relay, out_prefix + '_n3_performance.png')
    _plot_n3_throughput(direct, relay, out_prefix + '_n3_throughput.png')
    _plot_n3_composition(direct, relay, out_prefix + '_n3_composition.png')


def _print_category_breakdown(rows, label):
    """
    Mostra, por categoria do slot alignment, os fluxos (src→dst:porta) que a
    compõem. Serve para perceber EXACTAMENTE que pacotes são — em especial o
    que cai na categoria 'Non-video TCP (>200B, e.g. N3 control)'.
    """
    from collections import Counter
    cat_flows = defaultdict(Counter)
    for r in rows:
        cat = _packet_category(r)
        flow = f"{r['src']}→{r['dst']} :{r['dport'] if r['dport'] else '?'}"
        cat_flows[cat][flow] += 1

    print(f"\n─── N3 [{label}]: composição por categoria (fluxos principais) ──────────")
    for cat, _ in SLOT_CATS:
        flows = cat_flows.get(cat)
        if not flows:
            continue
        total = sum(flows.values())
        print(f"  {cat}  —  {total} pacotes")
        for flow, n in flows.most_common(4):
            print(f"      {n:>7}  {flow}")


def _significance(src, proto):
    if src == '172.20.10.1' and proto == 'TCP':
        return '← N1 directo via TDMA TCP (encapsulado)'
    if src == '10.0.0.1' and ('UDP' in proto or proto == 'MPEG TS'):
        return '← relay ip_forward: TUN src N1→N3 via N2 (raw MPEG TS, bypass TDMA)'
    if src == '172.20.10.2' and proto == 'TCP':
        return '← N2 TDMA slot próprio (TCP encapsulado)'
    if src == '172.20.10.2' and 'UDP' in proto:
        return '← N2 relay via ip_forward (raw MPEG TS)'
    if proto == 'RX':
        return '← beacon TDMA controlo'
    return ''


# ── Helpers de classificação de vídeo em N3 ───────────────────────────────────
def _is_video(r):
    """
    Pacotes de vídeo que chegam a N3, independentemente do caminho:
      - directo: TDMA TCP com dados (plen > 200B, não ACKs)
      - relay:   MPEG TS / UDP raw via ip_forward
    """
    return (r['ptype'] == 'tdma_tcp' and r['plen'] > 200) or r['ptype'] == 'video_udp'


def _video_stream(rows):
    """Devolve (timestamps_ms_ordenados, tamanhos) dos pacotes de vídeo."""
    vid = sorted((r for r in rows if _is_video(r)), key=lambda r: r['ts_ms'])
    ts  = np.array([r['ts_ms'] for r in vid])
    plen = np.array([r['plen'] for r in vid])
    return ts, plen


# ── 1) Alinhamento de slots TDMA ──────────────────────────────────────────────
def _circular_mean(pos, period=FRAME_MS):
    """Média circular de posições no frame (lida com o wrap em 0/period)."""
    if len(pos) == 0:
        return 0.0
    ang = 2 * np.pi * pos / period
    m = np.arctan2(np.sin(ang).mean(), np.cos(ang).mean())
    return (m / (2 * np.pi) * period) % period


def is_tdma_beacon(r):
    """
    True se for um beacon MATRIX. Os beacons são UDP nas portas 7001-7003 (107B),
    mas o Wireshark dissecta as portas 7000-7009 como protocolo RX (AFS) e, conforme
    os bytes do beacon, mostra-os ora como '[Malformed Packet]' ora como
    'ACK 0 ... Call: <timestamp>'. NÃO são pacotes RX a sério nem RX-ACKs — são
    TODOS beacons. Por isso classificamos qualquer pacote RX como beacon.
    """
    return r['proto'] == 'RX'


def _n1_beacon_pos(rows):
    """
    Posição (mod 150ms) dos beacons MATRIX do N1. Marca o slot de N1 — referência
    para alinhar o eixo. Devolve None se não houver beacons do N1.
    """
    bt = np.array([r['ts_ms'] for r in rows
                   if r['src'] == '172.20.10.1' and is_tdma_beacon(r)])
    if len(bt) == 0:
        return None
    return _circular_mean(bt % FRAME_MS)


def _align_offset(rows):
    """
    Offset a aplicar às posições no frame para alinhar o eixo com o início real
    do slot de N1. Preferência: beacon do N1 (marca o início do seu slot → 0 ms).
    Fallback: média circular da rajada de vídeo (centra no meio do slot N1, 25ms).
    Cada captura tem o seu próprio offset (t0 do Wireshark é independente).
    """
    b = _n1_beacon_pos(rows)
    if b is not None:
        return -b, 'aligned to N1 beacon'
    vts, _ = _video_stream(rows)
    if len(vts):
        return 25.0 - _circular_mean(vts % FRAME_MS), 'aligned to N1 video burst'
    return 0.0, 'raw capture t0 (no reference)'


# categorias de pacotes para colorir o slot alignment.
# Cada categoria explica O QUE é:
#   Video N1→N3        — fluxo de vídeo real (só N1 o gera; é o que prova o slot)
#   TDMA control (RX)  — beacons MATRIX + acks do protocolo RX (1 por nó por frame)
#   Non-video TCP      — TCP grande que NÃO é vídeo (ex: N3 a enviar controlo p/ N1/N2)
#   TCP ACK / small    — ACKs pequenos do TCP do vídeo
#   Control/telemetry  — canal de controlo/telemetria UDP (portas 9000-9002)
#   Other              — ruído do SO (mDNS/SSDP/ARP), sem relação com o mesh
SLOT_CATS = [
    ('Video N1→N3', '#4CAF50'),
    ('TDMA control (RX beacons/acks)', '#FF9800'),
    ('Non-video TCP (>200B, e.g. N3 control)', '#5C6BC0'),
    ('TCP ACK / small', '#90A4AE'),
    ('Control/telemetry (UDP 9000-9002)', '#AB47BC'),
    ('Other (mDNS/SSDP/ARP)', '#CFCFCF'),
]


def _packet_category(r):
    """
    Classifica um pacote. CRÍTICO: 'Video N1→N3' é APENAS o fluxo de vídeo real
    (origem N1, destino N3). TCP grande de outros nós (ex: N3→N1 controlo) NÃO é
    vídeo. Telemetria (UDP 9000-9002) tem categoria própria; 'Other' é só ruído
    do SO (mDNS/SSDP/ARP).
    """
    is_n1_to_n3 = r['src_node'] == 1 and r['dst_node'] == 3
    if r['ptype'] == 'video_udp' and is_n1_to_n3:
        return 'Video N1→N3'
    if r['ptype'] == 'tdma_tcp' and r['plen'] > 200 and is_n1_to_n3:
        return 'Video N1→N3'
    if r['proto'] == 'RX':
        return 'TDMA control (RX beacons/acks)'
    if r['ptype'] == 'tdma_tcp' and r['plen'] > 200:
        return 'Non-video TCP (>200B, e.g. N3 control)'
    if r['proto'] == 'TCP':
        return 'TCP ACK / small'
    if r['dport'] in (9000, 9001, 9002):
        return 'Control/telemetry (UDP 9000-9002)'
    return 'Other (mDNS/SSDP/ARP)'


def _plot_n3_slot_alignment(direct, relay, out_path):
    """
    Histograma da posição de TODOS os pacotes dentro do frame de 150ms,
    COLORIDO POR CATEGORIA (vídeo, controlo TDMA, ACKs TCP, outros) — mostra a
    estrutura TDMA completa e o que ocupa cada slot.

    Cada captura é alinhada com a SUA própria referência (beacon do N1), porque
    são capturas independentes com t0 diferentes. Os dois painéis ficam lado a
    lado, cada um com o seu eixo X, para comparação directo vs relay.
    """
    d_off, d_note = _align_offset(direct)
    r_off, r_note = _align_offset(relay)

    bins = np.arange(0, FRAME_MS + 3, 3)
    fig, axes = plt.subplots(1, 2, figsize=(15, 6))
    fig.suptitle('TDMA Frame Slot Alignment at N3\n'
                 'All packets by category — position within 150 ms frame (each capture aligned independently)',
                 fontsize=14, fontweight='bold')

    slots = [(0, 50, 'N1 slot\n(0–50 ms)', '#2196F3'),
             (50, 100, 'N2 slot\n(50–100 ms)', '#7E57C2'),
             (100, 150, 'N3 slot\n(100–150 ms)', '#F44336')]

    for ax, rows, off, title, note in [
        (axes[0], direct, d_off, f'Direct Link  (n = {len(direct):,} packets)', d_note),
        (axes[1], relay,  r_off, f'Relay via ip_forward  (n = {len(relay):,} packets)', r_note),
    ]:
        # posições por categoria
        by_cat = defaultdict(list)
        for r in rows:
            by_cat[_packet_category(r)].append((r['ts_ms'] + off) % FRAME_MS)
        data   = [by_cat[c] for c, _ in SLOT_CATS]
        colors = [col for _, col in SLOT_CATS]

        for a, b, lab, scol in slots:
            ax.axvspan(a, b, alpha=0.06, color=scol)
            ax.axvline(b, color='gray', ls='--', lw=1, alpha=0.6)
            ax.text((a + b) / 2, 0.97, lab, transform=ax.get_xaxis_transform(),
                    ha='center', va='top', fontsize=9, color=scol,
                    bbox=dict(boxstyle='round', facecolor='white', edgecolor=scol, alpha=0.9))
        ax.hist(data, bins=bins, stacked=True, color=colors,
                label=[c for c, _ in SLOT_CATS], edgecolor='none')
        ax.set_xlabel('Position within TDMA frame (ms)', fontsize=11)
        ax.set_ylabel('Packet count', fontsize=11)
        ax.set_title(title, fontsize=12, fontweight='bold')
        ax.grid(axis='y', alpha=0.2)
        ax.set_xlim(0, FRAME_MS)
        ax.legend(fontsize=8, loc='upper center')
        ax.text(0.99, 0.02, f'* {note}', transform=ax.transAxes, ha='right',
                fontsize=8, style='italic', color='gray')

    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"[PLOT] {out_path}")


# ── 2) Comparação de performance ──────────────────────────────────────────────
def _video_metrics(rows):
    """Métricas agregadas do fluxo de vídeo numa captura."""
    ts, plen = _video_stream(rows)
    if len(ts) < 2:
        return dict(packets=len(ts), duration=0, throughput=0, avg_ia=0, p95_ia=0)
    duration = (ts[-1] - ts[0]) / 1000.0
    throughput = plen.sum() * 8 / 1000.0 / duration if duration > 0 else 0
    ia = np.diff(ts)
    return dict(packets=len(ts), duration=duration, throughput=throughput,
                avg_ia=float(np.mean(ia)), p95_ia=float(np.percentile(ia, 95)))


def _plot_n3_performance(direct, relay, out_path):
    """Barras agrupadas comparando métricas directo vs relay."""
    dm = _video_metrics(direct)
    rm = _video_metrics(relay)

    labels = ['Video packets\nreceived', 'Capture\nduration (s)',
              'Avg throughput\n(kbps)', 'Avg inter-arrival\n(ms)',
              'P95 inter-arrival\n(ms)']
    dv = [dm['packets'], dm['duration'], dm['throughput'], dm['avg_ia'], dm['p95_ia']]
    rv = [rm['packets'], rm['duration'], rm['throughput'], rm['avg_ia'], rm['p95_ia']]

    x = np.arange(len(labels))
    w = 0.38
    fig, ax = plt.subplots(figsize=(13, 6))
    bd = ax.bar(x - w/2, dv, w, label='Direct (N1→N3)', color='#2196F3')
    br = ax.bar(x + w/2, rv, w, label='Relay (N1→N2→N3)', color='#4CAF50')

    for bars in (bd, br):
        for b in bars:
            h = b.get_height()
            ax.annotate(f'{h:.1f}' if h < 1000 else f'{h:.0f}',
                        xy=(b.get_x() + b.get_width()/2, h),
                        xytext=(0, 4), textcoords='offset points',
                        ha='center', fontsize=10, fontweight='bold')

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=10)
    ax.set_ylabel('Value', fontsize=12)
    ax.set_title('Performance Comparison — Direct Link vs. Relay Path at Node 3',
                 fontsize=14, fontweight='bold')
    ax.legend(fontsize=11)
    ax.grid(axis='y', alpha=0.2)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"[PLOT] {out_path}")


# ── 3) Throughput ao longo do tempo ───────────────────────────────────────────
def _throughput_series(rows, bin_s=1.0):
    """Throughput (kbps) por janela de bin_s segundos."""
    ts, plen = _video_stream(rows)
    if len(ts) == 0:
        return np.array([]), np.array([])
    t_s = ts / 1000.0
    t0, t1 = t_s[0], t_s[-1]
    edges = np.arange(t0, t1 + bin_s, bin_s)
    bytes_per_bin, _ = np.histogram(t_s, bins=edges, weights=plen)
    kbps = bytes_per_bin * 8 / 1000.0 / bin_s
    centers = (edges[:-1] + edges[1:]) / 2 - t0
    return centers, kbps


def _plot_n3_throughput(direct, relay, out_path):
    """Linha do throughput observado ao longo do tempo."""
    dt, dk = _throughput_series(direct)
    rt, rk = _throughput_series(relay)

    fig, ax = plt.subplots(figsize=(13, 5.5))
    if len(dt):
        davg = dk.mean()
        ax.plot(dt, dk, color='#2196F3', lw=1.8,
                label=f'Direct — TDMA TCP stream  (avg {davg:.0f} kbps)')
        ax.fill_between(dt, dk, alpha=0.12, color='#2196F3')
        ax.axhline(davg, color='#2196F3', ls=':', lw=1, alpha=0.7)
    if len(rt):
        ravg = rk.mean()
        ax.plot(rt, rk, color='#2E7D32', lw=1.8,
                label=f'Relay — Raw MPEG TS via ip_forward  (avg {ravg:.0f} kbps)')
        ax.fill_between(rt, rk, alpha=0.12, color='#2E7D32')
        ax.axhline(ravg, color='#2E7D32', ls=':', lw=1, alpha=0.7)

    ax.set_xlabel('Time (s)', fontsize=12)
    ax.set_ylabel('Throughput (kbps)', fontsize=12)
    ax.set_title('Observed Throughput at N3 — Direct Link vs. Relay Path',
                 fontsize=14, fontweight='bold')
    ax.set_ylim(bottom=0)
    ax.set_xlim(left=0)
    ax.legend(fontsize=11, loc='center')
    ax.grid(alpha=0.2)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"[PLOT] {out_path}")


# ── 4) Composição de tráfego ──────────────────────────────────────────────────
def _traffic_composition(rows):
    """Conta pacotes por categoria na captura."""
    cats = {'TDMA TCP\n(encapsulated video)': 0, 'TDMA Beacons\n(control)': 0,
            'UDP / MPEG TS\n(ip_forward raw)': 0, 'TCP ACKs /\ncontrol': 0}
    for r in rows:
        if r['ptype'] == 'tdma_tcp' and r['plen'] > 200:
            cats['TDMA TCP\n(encapsulated video)'] += 1
        elif r['ptype'] == 'video_udp':
            cats['UDP / MPEG TS\n(ip_forward raw)'] += 1
        elif r['proto'] == 'RX':
            cats['TDMA Beacons\n(control)'] += 1
        elif r['proto'] == 'TCP':
            cats['TCP ACKs /\ncontrol'] += 1
    return cats


def _plot_n3_composition(direct, relay, out_path):
    """Dois subplots de barras: composição de tráfego directo vs relay."""
    dc = _traffic_composition(direct)
    rc = _traffic_composition(relay)
    labels = list(dc.keys())
    colors = ['#2196F3', '#78909C', '#2E7D32', '#B0BEC5']

    ymax = max(max(dc.values()), max(rc.values())) * 1.15
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=True)
    fig.suptitle('Traffic Composition at N3: Direct vs. Relay',
                 fontsize=14, fontweight='bold')

    for ax, counts, title, hl in [
        (axes[0], dc, 'Direct Link  (N1 → N3)', '#2196F3'),
        (axes[1], rc, 'Relay Path  (N1 → N2 → N3)', '#2E7D32'),
    ]:
        vals = [counts[l] for l in labels]
        # destaca o fluxo de vídeo dominante de cada modo
        bcolors = list(colors)
        bars = ax.bar(range(len(labels)), vals, color=bcolors)
        for b, v in zip(bars, vals):
            ax.annotate(f'{v:,}', xy=(b.get_x() + b.get_width()/2, v),
                        xytext=(0, 4), textcoords='offset points',
                        ha='center', fontsize=11, fontweight='bold')
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, fontsize=9)
        ax.set_title(title, fontsize=12, fontweight='bold', color=hl)
        ax.set_ylim(0, ymax)
        ax.grid(axis='y', alpha=0.2)
    axes[0].set_ylabel('Number of Packets', fontsize=12)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"[PLOT] {out_path}")


# ── Análise N2 — transformação TCP→UDP e latência ip_forward ──────────────────
def analyse_n2(n2_csv, out_prefix):
    """
    Mede a latência do relay em N2: tempo entre RECEBER o pacote (TCP de N1)
    e LIBERTÁ-LO reencaminhado (MPEG TS para N3 via ip_forward).

    Para cada pacote de saída encontra o último pacote de dados TCP que chegou
    antes dele (o que completou a receção) e calcula Δt = saída − entrada.
    """
    rows = load_csv(n2_csv)

    # ENTRADA: dados de vídeo encapsulados em TDMA TCP que chegam de N1.
    # Filtra ACKs puros (~66B): só segmentos com dados podem "completar" um pacote.
    tcp_in = [r for r in rows
              if r['src_node'] == 1 and r['dst_node'] == 2
              and r['proto'] == 'TCP' and r['plen'] > 100]
    # SAÍDA: o relay é TRANSPARENTE (ip_forward sem NAT) — o vídeo reencaminhado
    # mantém os IPs originais (src=10.0.0.1 N1, dst=10.0.0.3 N3) e aparece como
    # MPEG TS / UDP porta 5000. NÃO sai como 172.20.10.2→172.20.10.3.
    udp_out = [r for r in rows
               if r['ptype'] == 'video_udp'
               and r['src_node'] == 1 and r['dst_node'] == 3]

    print("\n─── N2: Latência do relay (receber → libertar) ─────────────────────────")
    print(f"  Entrada  TCP dados (N1→N2, TDMA):                 {len(tcp_in):>5} pacotes")
    print(f"  Saída    MPEG TS  (N1→N3, ip_forward transparente): {len(udp_out):>5} pacotes")

    if not (tcp_in and udp_out):
        print("\n[WARN] Sem ambos os fluxos — impossível medir latência.")
        return

    # emparelha cada saída com a última entrada de dados que a precedeu
    deltas = []
    j = 0
    for udp in udp_out:
        while j < len(tcp_in) - 1 and tcp_in[j + 1]['ts_ms'] < udp['ts_ms']:
            j += 1
        if tcp_in[j]['ts_ms'] < udp['ts_ms']:
            dt = udp['ts_ms'] - tcp_in[j]['ts_ms']
            if dt < 50:  # ignora gaps grandes (rajadas/frames diferentes)
                deltas.append(dt)

    if not deltas:
        print("\n[WARN] Não foi possível emparelhar entrada/saída.")
        return

    deltas = np.array(deltas)
    print(f"\n  Δt recebe → liberta  (latência ip_forward):")
    print(f"    n        = {len(deltas)}")
    print(f"    média    = {deltas.mean():.3f} ms")
    print(f"    mediana  = {np.median(deltas):.3f} ms")
    print(f"    σ        = {deltas.std():.3f} ms")
    print(f"    min      = {deltas.min():.3f} ms")
    print(f"    P95      = {np.percentile(deltas, 95):.3f} ms")
    print(f"    P99      = {np.percentile(deltas, 99):.3f} ms")
    print(f"    max      = {deltas.max():.3f} ms")
    print(f"\n  → relay quase instantâneo: o ip_forward do kernel encaminha sem"
          f" passar pela aplicação.")

    _plot_n2_latency(deltas, out_prefix + '_n2_latency.png')


def _plot_n2_latency(deltas, out_path):
    """
    Single histogram of the N2 relay forwarding delay (receive -> release),
    with all metrics shown in a side box.
    """
    mu   = deltas.mean()
    med  = np.median(deltas)
    sd   = deltas.std()
    dmin = deltas.min()
    dmax = deltas.max()
    p95  = np.percentile(deltas, 95)
    p99  = np.percentile(deltas, 99)

    fig, ax = plt.subplots(figsize=(11, 5))

    # limit the x axis to the bulk of the distribution (tail goes into the box)
    xmax = max(p99 * 1.5, 0.5)
    bins = np.linspace(0, xmax, 60)
    ax.hist(deltas, bins=bins, color='#4CAF50', alpha=0.85, edgecolor='none')
    ax.axvline(med, color='#1565C0', lw=1.8, label=f'median = {med:.3f} ms')
    ax.axvline(mu,  color='red',     lw=1.8, ls='--', label=f'mean = {mu:.3f} ms')

    ax.set_title('N2 relay forwarding latency', fontsize=13, fontweight='bold')
    ax.set_xlabel('Forwarding delay  Δt  (ms)', fontsize=11)
    ax.set_ylabel('Packets', fontsize=11)
    ax.set_xlim(0, xmax)
    ax.legend(fontsize=9, loc='upper right')
    ax.grid(axis='y', alpha=0.3)

    # side box with every metric, in ms
    txt = (f'n       = {len(deltas)}\n'
           f'mean    = {mu:.3f} ms\n'
           f'median  = {med:.3f} ms\n'
           f'std     = {sd:.3f} ms\n'
           f'min     = {dmin:.3f} ms\n'
           f'P95     = {p95:.3f} ms\n'
           f'P99     = {p99:.3f} ms\n'
           f'max     = {dmax:.3f} ms')
    ax.text(0.985, 0.74, txt, transform=ax.transAxes, ha='right', va='top',
            fontsize=9, family='monospace',
            bbox=dict(boxstyle='round', facecolor='white', alpha=0.9))

    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"[PLOT] {out_path}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description='Análise de relay TDMA a partir de CSVs Wireshark',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  # Captura em N3 — directo vs relay
  python3 tdma_relay_analysis.py --n3 direct.csv relay.csv

  # Captura em N2 — transformação TCP→UDP
  python3 tdma_relay_analysis.py --n2 n2_relay.csv

  # Ambos
  python3 tdma_relay_analysis.py --n2 n2_relay.csv --n3 direct.csv relay.csv
""")
    parser.add_argument('--n3', nargs=2, metavar=('DIRECT_CSV', 'RELAY_CSV'),
                        help='Capturas em N3: directo e relay')
    parser.add_argument('--n2', metavar='N2_CSV',
                        help='Captura em N2 durante relay (wlan0)')
    parser.add_argument('--out', default='relay_analysis',
                        help='Prefixo dos ficheiros de saída (default: relay_analysis)')
    args = parser.parse_args()

    if not args.n3 and not args.n2:
        parser.print_help()
        sys.exit(1)

    if args.n2:
        if not os.path.exists(args.n2):
            print(f"ERRO: {args.n2} não encontrado"); sys.exit(1)
        analyse_n2(args.n2, args.out)

    if args.n3:
        for f in args.n3:
            if not os.path.exists(f):
                print(f"ERRO: {f} não encontrado"); sys.exit(1)
        analyse_n3(args.n3[0], args.n3[1], args.out)

    print(f"\n[OK] Gráficos guardados com prefixo '{args.out}'")


if __name__ == '__main__':
    main()
