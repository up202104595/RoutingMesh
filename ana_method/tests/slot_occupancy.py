#!/usr/bin/env python3
"""
slot_occupancy.py — Análise de colocação dos pacotes por slot TDMA (método Ana).

Prova que, no método da Ana (meshnode_ana), os nós também respeitam os seus
slots: lê uma captura Wireshark (CSV) dos STATE packets, enrola cada instante
de transmissão ao frame de 150 ms, remove a rotação comum do frame (o
sincronizador avança todos os slots por um valor comum em cada ronda) e mostra
que cada nó fica confinado ao seu slot.

Gera dois gráficos, equivalentes aos do método Miguel:
  • <out>_scatter.png  — cru, mostra a deriva diagonal (~18 ms/s)
  • <out>_derot.png    — de-rotado, cada nó fixo no seu slot (evidência)

Como capturar (no N3, durante operação normal da mesh):
  sudo tcpdump -i wlan0 -w state.pcap 'udp portrange 7001-7003'
  # depois no Wireshark: File → Export Packet Dissections → As CSV
  # colunas: No., Time, Source, Destination, Protocol, Length, Info

Uso:
  python3 slot_occupancy.py state.csv --out figs/ana_slots
  python3 slot_occupancy.py state.csv --phy-prefix 172.20.10 --nodes 3
"""

import sys, os, csv, argparse
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

FRAME_MS = 150.0
SLOT_MS  = 50.0
COLORS   = {1: '#2196F3', 2: '#4CAF50', 3: '#F44336'}


def load_state(path, phy_prefix, max_len):
    """Devolve (t_seconds, node) dos STATE packets, identificados pelo IP de
    origem (172.20.10.i -> nó i) e tamanho pequeno (exclui vídeo/RTT)."""
    ts, nd = [], []
    with open(path, newline='', encoding='utf-8-sig') as f:
        r = csv.DictReader(f)
        norm = {h.strip().strip('"').lower(): h for h in (r.fieldnames or [])}
        tc, sc, lc = norm.get('time'), norm.get('source'), norm.get('length')
        if not (tc and sc):
            print('ERRO: faltam colunas Time/Source no CSV'); sys.exit(1)
        for row in r:
            try:
                t = float(row[tc].strip().strip('"'))
                src = row[sc].strip().strip('"')
                L = int(row[lc].strip().strip('"')) if lc else 0
            except (ValueError, KeyError):
                continue
            if not src.startswith(phy_prefix + '.'):
                continue
            if lc and L > max_len:        # exclui vídeo (>200B) e outros
                continue
            try:
                node = int(src.rsplit('.', 1)[1])
            except ValueError:
                continue
            ts.append(t); nd.append(node)
    return np.array(ts), np.array(nd)


def best_rotation(ts, nd, nodes):
    """Estima a rotação comum (ms/s) que maximiza a concentração angular
    por nó (estimador circular robusto). Devolve a taxa em ms/s."""
    t0 = ts.min()
    rel = ts - t0
    best_rate, best_score = 0.0, -1.0
    # varre +-40 ms/s (a deriva típica é ~18 ms/s)
    for rate in np.linspace(-40, 40, 1601):
        phi = ((ts * 1000.0 - rate * rel) % FRAME_MS) / FRAME_MS * 2 * np.pi
        score = 0.0
        for n in nodes:
            m = nd == n
            if m.sum() < 2:
                continue
            score += abs(np.mean(np.exp(1j * phi[m])))   # comprimento resultante
        if score > best_score:
            best_score, best_rate = score, rate
    return best_rate


def wrap(ts, nd, rate):
    """Fase no frame (ms) após remover a rotação 'rate' (ms/s)."""
    rel = ts - ts.min()
    return (ts * 1000.0 - rate * rel) % FRAME_MS


def anchor(phi, nd, nodes):
    """A fase absoluta do frame é arbitrária (não há relógio global). Aplica um
    deslocamento comum a TODAS as fases para alinhar o cluster do nó mais baixo
    ao centro do seu slot, deixando a estrutura cíclica legível. Não altera o
    espaçamento relativo entre nós (o que de facto prova a sincronização)."""
    n0 = nodes[0]
    ang = phi[nd == n0] / FRAME_MS * 2 * np.pi
    center = (np.angle(np.mean(np.exp(1j * ang))) % (2 * np.pi)) / (2 * np.pi) * FRAME_MS
    target = (n0 - 0.5) * SLOT_MS            # centro do slot do nó n0
    return (phi + (target - center)) % FRAME_MS


def occupancy_stats(phi, nd, nodes):
    """Para cada nó, devolve (centro, desvio circular ms, % no slot atribuído)."""
    out = {}
    for n in nodes:
        m = nd == n
        if m.sum() == 0:
            continue
        ang = phi[m] / FRAME_MS * 2 * np.pi
        R = abs(np.mean(np.exp(1j * ang)))
        std_ms = np.sqrt(max(0.0, -2 * np.log(R))) / (2 * np.pi) * FRAME_MS
        center = (np.angle(np.mean(np.exp(1j * ang))) % (2 * np.pi)) / (2 * np.pi) * FRAME_MS
        lo, hi = (n - 1) * SLOT_MS, n * SLOT_MS
        in_slot = 100.0 * np.mean((phi[m] >= lo) & (phi[m] < hi))
        out[n] = (center, std_ms, in_slot, int(m.sum()))
    return out


def plot(ts, nd, phi_raw, phi_derot, nodes, out_base, title):
    rel = ts - ts.min()
    rounds = (rel * 1000.0 / FRAME_MS).astype(int)
    for tag, phi in [('scatter', phi_raw), ('derot', phi_derot)]:
        fig, ax = plt.subplots(figsize=(11, 5))
        for n in nodes:
            m = nd == n
            ax.scatter(phi[m], rounds[m], s=10, alpha=0.7,
                       color=COLORS.get(n, '#777'), label=f'Node {n}')
        for b in range(0, int(FRAME_MS) + 1, int(SLOT_MS)):
            ax.axvline(b, color='gray', ls='--', lw=1, alpha=0.6)
        for n in nodes:
            ax.axvspan((n - 1) * SLOT_MS, n * SLOT_MS, alpha=0.05,
                       color=COLORS.get(n, '#777'))
        ax.set_xlim(0, FRAME_MS)
        ax.set_xlabel('Position within TDMA frame (ms)  [wrapped 0-150 ms]')
        ax.set_ylabel('TDMA round')
        ax.legend(loc='center left', bbox_to_anchor=(1.01, 0.5), fontsize=9)
        if title:
            ax.set_title(title + (' (raw)' if tag == 'scatter' else ' (de-rotated)'),
                         fontsize=12, fontweight='bold')
        ax.grid(axis='x', alpha=0.3)
        plt.tight_layout()
        out = f'{out_base}_{tag}.png'
        os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
        plt.savefig(out, dpi=150); plt.close()
        print(f'[PLOT] {out}')


def main():
    ap = argparse.ArgumentParser(description='Slot occupancy (Ana method)')
    ap.add_argument('csv', help='Wireshark CSV dos STATE packets')
    ap.add_argument('--out', default='ana_slots', help='base do nome de saída')
    ap.add_argument('--phy-prefix', default='172.20.10',
                    help='prefixo físico (default 172.20.10; use 192.168.2 se build assim)')
    ap.add_argument('--nodes', type=int, default=3, help='nº de nós')
    ap.add_argument('--max-len', type=int, default=200,
                    help='tamanho máx. do pacote de controlo (exclui vídeo)')
    ap.add_argument('--title', default=None)
    args = ap.parse_args()

    ts, nd = load_state(args.csv, args.phy_prefix, args.max_len)
    if len(ts) < 4:
        print(f'[ERRO] só {len(ts)} STATE packets encontrados. '
              f'Confirma o prefixo físico (--phy-prefix) e o filtro de captura.')
        sys.exit(1)
    order = np.argsort(ts); ts, nd = ts[order], nd[order]
    nodes = sorted(set(int(x) for x in nd) & set(range(1, args.nodes + 1)))

    rate = best_rotation(ts, nd, nodes)
    phi_raw   = wrap(ts, nd, 0.0)
    phi_derot = anchor(wrap(ts, nd, rate), nd, nodes)

    print(f'\nCaptura: {len(ts)} STATE packets, nós {nodes}, '
          f'duração {ts[-1]-ts[0]:.0f}s')
    print(f'Rotação comum estimada: {rate:+.1f} ms/s\n')
    print(f'{"Nó":>3} {"centro(ms)":>11} {"σ(ms)":>7} {"% no slot":>10} {"pkts":>6}')
    stats = occupancy_stats(phi_derot, nd, nodes)
    for n in nodes:
        c, s, ins, k = stats[n]
        print(f'{n:>3} {c:>11.1f} {s:>7.1f} {ins:>9.1f}% {k:>6}')
    print()

    plot(ts, nd, phi_raw, phi_derot, nodes, args.out, args.title)
    print('Interpretação: no gráfico de-rotado cada nó deve ficar no seu slot '
          '[(n-1)*50, n*50] ms, em ordem cíclica N1->N2->N3 — prova de que o '
          'método da Ana também respeita os slots TDMA.')


if __name__ == '__main__':
    main()
