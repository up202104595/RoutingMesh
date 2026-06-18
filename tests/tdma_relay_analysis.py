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

    _plot_n3_comparison(d_counts, r_counts, out_prefix + '_n3_protocol.png')
    _plot_interarrival_comparison(direct, relay, out_prefix + '_n3_interarrival.png')


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


def _plot_n3_comparison(d_counts, r_counts, out_path):
    """Gráfico de barras: protocolos que chegam a N3 directo vs relay."""
    # agrupa por protocolo
    def proto_bytes(counts):
        pg = defaultdict(int)
        for (src, proto), n in counts.items():
            label = f"{proto}\n({src})"
            pg[label] += n
        return pg

    d_pg = proto_bytes(d_counts)
    r_pg = proto_bytes(r_counts)

    all_labels = sorted(set(d_pg) | set(r_pg))

    x  = np.arange(len(all_labels))
    w  = 0.35
    dv = [d_pg.get(l, 0) for l in all_labels]
    rv = [r_pg.get(l, 0) for l in all_labels]

    fig, ax = plt.subplots(figsize=(10, 5))
    bars_d = ax.bar(x - w/2, dv, w, label='Directo (N1→N3)', color='#2196F3', alpha=0.85)
    bars_r = ax.bar(x + w/2, rv, w, label='Relay (N1→N2→N3)', color='#4CAF50', alpha=0.85)

    ax.set_xticks(x)
    ax.set_xticklabels(all_labels, fontsize=9)
    ax.set_ylabel('Nº de pacotes')
    ax.set_title('N3 — Protocolo recebido: Directo vs Relay\n'
                 'Em relay o src muda para N2 (172.20.10.2) e o protocolo passa a UDP/MPEG TS',
                 fontsize=10)
    ax.legend()
    ax.grid(axis='y', alpha=0.3)

    # anotação explicativa
    ax.annotate('TDMA encapsulado\n(protocolo do mesh)',
                xy=(0, 0), xytext=(0.18, 0.85), textcoords='axes fraction',
                fontsize=8, color='#2196F3',
                arrowprops=None)
    ax.annotate('ip_forward raw\n(bypass TDMA)',
                xy=(0, 0), xytext=(0.62, 0.85), textcoords='axes fraction',
                fontsize=8, color='#4CAF50',
                arrowprops=None)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"[PLOT] {out_path}")


def _plot_interarrival_comparison(direct, relay, out_path):
    """Histograma de inter-arrivals: directo vs relay sobrepostos."""
    def ias(rows):
        # directo: TCP de N1 (172.20.10.1) — TDMA encapsulado, plen > 200B (dados, não ACKs)
        # relay:   MPEG TS de TUN (10.0.0.1) — ip_forward raw
        video = sorted([r['ts_ms'] for r in rows
                        if r['ptype'] in ('video_udp', 'tdma_tcp') and r['plen'] > 200])
        return [video[i] - video[i-1] for i in range(1, len(video))]

    d_ia = ias(direct)
    r_ia = ias(relay)

    if not d_ia or not r_ia:
        print("[WARN] Inter-arrivals insuficientes para comparação")
        return

    bins = np.arange(0, 320, 5)
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
    fig.suptitle('Inter-arrival dos pacotes de vídeo em N3\nDirecto vs Relay — padrão TDMA preservado',
                 fontsize=11, fontweight='bold')

    for ax, ia, label, color in [
        (axes[0], d_ia, 'Directo (N1→N3)', '#2196F3'),
        (axes[1], r_ia, 'Relay (N1→N2→N3 via ip_forward)', '#4CAF50'),
    ]:
        ax.hist(ia, bins=bins, color=color, alpha=0.8, edgecolor='none')
        # marcas TDMA
        for ms in [50, 100, 150, 200, 250, 300]:
            ax.axvline(x=ms, color='black', lw=0.8, linestyle='--', alpha=0.5)
        ax.axvspan(130, 160, alpha=0.08, color='orange', label='Zona frame ~150ms')
        n = len(ia)
        burst = sum(1 for x in ia if x < 15)
        ax.set_ylabel('Pacotes')
        ax.set_title(f'{label}   n={n}   rajada(<15ms): {burst} ({100*burst/n:.0f}%)',
                     fontsize=9)
        ax.legend(fontsize=8)
        ax.grid(axis='x', alpha=0.3)

        mu = np.mean(ia); p95 = np.percentile(ia, 95)
        ax.text(0.98, 0.92, f'μ={mu:.1f}ms  P95={p95:.0f}ms',
                transform=ax.transAxes, ha='right', fontsize=8,
                bbox=dict(boxstyle='round', facecolor='white', alpha=0.7))

    axes[-1].set_xlabel('Inter-arrival (ms)', fontsize=11)
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
    Gráfico único e claro da latência do relay em N2:
      esquerda  — histograma do Δt (recebe → liberta)
      direita   — CDF, com P50/P95/P99 marcados
    """
    mu  = deltas.mean()
    med = np.median(deltas)
    p95 = np.percentile(deltas, 95)
    p99 = np.percentile(deltas, 99)

    fig, (axh, axc) = plt.subplots(1, 2, figsize=(13, 5))
    fig.suptitle('N2 — Latência do relay: tempo entre RECEBER (TCP de N1) e '
                 'LIBERTAR (MPEG TS para N3)\n'
                 'ip_forward do kernel — o pacote é reencaminhado sem passar pela aplicação',
                 fontsize=11, fontweight='bold')

    # ── histograma ──
    # limita o eixo a P99 para não esmagar a distribuição com a cauda
    xmax = max(p99 * 1.5, 0.5)
    bins = np.linspace(0, xmax, 60)
    axh.hist(deltas, bins=bins, color='#4CAF50', alpha=0.85, edgecolor='none')
    axh.axvline(med, color='#1565C0', lw=1.8, label=f'mediana = {med:.3f} ms')
    axh.axvline(mu,  color='red',     lw=1.8, ls='--', label=f'média = {mu:.3f} ms')
    axh.set_xlabel('Δt  recebe → liberta (ms)', fontsize=11)
    axh.set_ylabel('Nº de pacotes')
    axh.set_xlim(0, xmax)
    axh.set_title(f'Distribuição (n={len(deltas)})', fontsize=10)
    axh.legend(fontsize=9)
    axh.grid(axis='y', alpha=0.3)

    # ── CDF ──
    sd = np.sort(deltas)
    cdf = np.arange(1, len(sd) + 1) / len(sd)
    axc.plot(sd, cdf * 100, color='#4CAF50', lw=2)
    for val, lab, col in [(med, 'P50', '#1565C0'), (p95, 'P95', '#FF9800'),
                          (p99, 'P99', '#F44336')]:
        axc.axvline(val, color=col, lw=1.4, ls='--')
        axc.text(val, 5, f'{lab}\n{val:.2f}ms', color=col, fontsize=8,
                 ha='left', va='bottom')
    axc.set_xlabel('Δt  recebe → liberta (ms)', fontsize=11)
    axc.set_ylabel('Percentagem de pacotes (%)')
    axc.set_xlim(0, xmax)
    axc.set_ylim(0, 100)
    axc.set_title('CDF — fração reencaminhada em ≤ Δt', fontsize=10)
    axc.grid(alpha=0.3)

    # caixa-resumo
    txt = (f'média  = {mu:.3f} ms\nmediana= {med:.3f} ms\n'
           f'P95    = {p95:.3f} ms\nP99    = {p99:.3f} ms\nmax    = {deltas.max():.3f} ms')
    axc.text(0.97, 0.45, txt, transform=axc.transAxes, ha='right', va='top',
             fontsize=9, family='monospace',
             bbox=dict(boxstyle='round', facecolor='white', alpha=0.85))

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
