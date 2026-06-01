#!/usr/bin/env python3
"""
metrics_show.py — Mostra métricas ao vivo a partir de /var/log/routingmesh/metrics.jsonl

Uso:
  python3 metrics_show.py           # lê ficheiro ao vivo (tail -f)
  python3 metrics_show.py --summary # resumo do ficheiro completo
"""

import json
import time
import sys
import os
import signal
from collections import defaultdict

LOG_FILE = "/var/log/routingmesh/metrics.jsonl"

# ── Modo resumo ───────────────────────────────────────────────────────────────

def summary():
    if not os.path.exists(LOG_FILE):
        print(f"ERRO: {LOG_FILE} não existe. Inicia o serviço meshnode-metrics primeiro.")
        return

    pkts_sent      = 0
    pkts_delivered = 0
    pkts_relayed   = 0
    queue_drops    = 0
    peer_lost      = 0
    topo_changes   = 0
    recompute_times = []
    link_qualities  = defaultdict(list)  # node -> [quality]
    mst_edges       = []

    with open(LOG_FILE) as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            ev = r.get("event")
            if ev == "pkt_sent":       pkts_sent += 1
            elif ev == "pkt_delivered": pkts_delivered += 1
            elif ev == "pkt_relayed":   pkts_relayed += 1
            elif ev == "queue_overflow": queue_drops += 1
            elif ev == "peer_lost":     peer_lost += 1
            elif ev == "topology_changed": topo_changes += 1
            elif ev == "routing_recompute_us":
                recompute_times.append(r["us"])
            elif ev == "link_quality":
                link_qualities[r["node"]].append(r["quality"])
            elif ev == "mst_edge":
                mst_edges.append(r)

    print("╔══════════════════════════════════════════════════╗")
    print("║         RA-TDMAs+  Métricas — Resumo            ║")
    print("╠══════════════════════════════════════════════════╣")
    print(f"║  Pacotes enviados:     {pkts_sent:>8}                  ║")
    print(f"║  Pacotes entregues:    {pkts_delivered:>8}                  ║")
    print(f"║  Pacotes em relay:     {pkts_relayed:>8}                  ║")

    if pkts_sent > 0:
        pdr = (pkts_delivered / pkts_sent) * 100
        print(f"║  PDR (entregues/env):  {pdr:>7.1f}%                  ║")
    else:
        print(f"║  PDR:                       N/A                  ║")

    print(f"║  Drops (queue full):   {queue_drops:>8}                  ║")
    print(f"║  Peers perdidos:       {peer_lost:>8}                  ║")
    print(f"║  Mudanças topologia:   {topo_changes:>8}                  ║")
    print("╠══════════════════════════════════════════════════╣")

    if recompute_times:
        avg_rt = sum(recompute_times) / len(recompute_times)
        max_rt = max(recompute_times)
        min_rt = min(recompute_times)
        print(f"║  Routing recompute:                               ║")
        print(f"║    count={len(recompute_times):>4}  avg={avg_rt:>6.0f}µs  "
              f"min={min_rt:>5}µs  max={max_rt:>6}µs  ║")
    else:
        print(f"║  Routing recompute:   nenhum evento               ║")

    print("╠══════════════════════════════════════════════════╣")
    if link_qualities:
        print(f"║  Link Quality (média por nó vizinho):             ║")
        for node in sorted(link_qualities.keys()):
            qs = link_qualities[node]
            avg_q = sum(qs) / len(qs)
            print(f"║    Nó {node}: {avg_q:5.1f}  (amostras={len(qs)})                  ║")
    else:
        print(f"║  Link Quality:        nenhum dado                 ║")

    if mst_edges:
        print("╠══════════════════════════════════════════════════╣")
        print(f"║  Últimas MST edges:                               ║")
        seen = set()
        for e in reversed(mst_edges):
            key = (e.get("n1"), e.get("n2"))
            if key not in seen:
                seen.add(key)
                print(f"║    {e['n1']}-{e['n2']}: quality={e['quality']:>3}  cost={e['cost']:>3}        ║")
            if len(seen) >= 5:
                break

    print("╚══════════════════════════════════════════════════╝")


# ── Modo live (tail) ──────────────────────────────────────────────────────────

def live():
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    if not os.path.exists(LOG_FILE):
        print(f"A aguardar {LOG_FILE}...")
        while not os.path.exists(LOG_FILE):
            time.sleep(1)

    print(f"[METRICS LIVE] {LOG_FILE}")
    print(f"{'Timestamp':<14} {'Evento':<25} {'Detalhes'}")
    print("-" * 72)

    with open(LOG_FILE) as f:
        f.seek(0, 2)   # vai para o fim do ficheiro
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.1)
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue

            ts  = r.get("ts", 0)
            ev  = r.get("event", "?")
            ts_str = time.strftime("%H:%M:%S", time.localtime(ts))

            detail = ""
            if ev == "pkt_sent":
                detail = f"src={r.get('src')} dst={r.get('dst')} msg={r.get('msg_id')} {r.get('bytes')}B"
            elif ev == "pkt_delivered":
                detail = f"src={r.get('src')} dst={r.get('dst')} msg={r.get('msg_id')} {r.get('bytes')}B"
            elif ev == "pkt_relayed":
                detail = f"src={r.get('src')} dst={r.get('dst')}"
            elif ev == "routing_recompute_us":
                detail = f"{r.get('us')} µs"
            elif ev == "link_quality":
                detail = f"node={r.get('node')} quality={r.get('quality')}"
            elif ev == "mst_edge":
                detail = f"{r.get('n1')}-{r.get('n2')} quality={r.get('quality')} cost={r.get('cost')}"
            elif ev == "peer_lost":
                detail = f"peer={r.get('peer')}"
            elif ev == "peer_connected":
                detail = f"peer={r.get('peer')}"
            elif ev == "queue_overflow":
                detail = "drop!"
            elif ev == "route_relay":
                detail = f"relay={r.get('relay')} quality={r.get('quality')}"
            elif ev == "route_direct":
                detail = f"{r.get('dest_ip')} via {r.get('gw_ip')}"

            print(f"{ts_str:<14} {ev:<25} {detail}")


if __name__ == "__main__":
    if "--summary" in sys.argv:
        summary()
    else:
        live()
