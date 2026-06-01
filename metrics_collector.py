#!/usr/bin/env python3
"""
metrics_collector.py — Coleta métricas em tempo real dos logs do meshnode

Faz parse do stdout/stderr do meshnode via journald (ou pipe) e exporta
métricas para /var/log/routingmesh/metrics.jsonl (uma linha JSON por evento).

Uso:
  journalctl -u meshnode -f | python3 metrics_collector.py
  ou via serviço systemd (ver deploy/meshnode-metrics.service)
"""

import sys
import re
import json
import time
import os
import signal

LOG_DIR  = "/var/log/routingmesh"
LOG_FILE = os.path.join(LOG_DIR, "metrics.jsonl")

os.makedirs(LOG_DIR, exist_ok=True)

# ── Padrões de regex para cada métrica ───────────────────────────────────────

PATTERNS = [
    # Pacotes enviados via TCP na slot
    # [TCP-TX] MSG_DATA src=1 dst=3 msg_id=1042 512 bytes
    (re.compile(
        r'\[TCP-TX\] MSG_DATA src=(?P<src>\d+) dst=(?P<dst>\d+) '
        r'msg_id=(?P<msg_id>\d+) (?P<bytes>\d+) bytes'),
     "pkt_sent"),

    # Pacotes recebidos e entregues à TUN
    # [TCP-RX] MSG_DATA ENTREGUE src=1 dst=3 msg_id=1042 512 bytes
    (re.compile(
        r'\[TCP-RX\] MSG_DATA ENTREGUE src=(?P<src>\d+) dst=(?P<dst>\d+) '
        r'msg_id=(?P<msg_id>\d+) (?P<bytes>\d+) bytes'),
     "pkt_delivered"),

    # Pacotes em relay pelo kernel
    # [TCP-RX] RELAY src=1 dst=3
    (re.compile(
        r'\[TCP-RX\] RELAY src=(?P<src>\d+) dst=(?P<dst>\d+)'),
     "pkt_relayed"),

    # Tempo de recomputação de routing
    # [ROUTING] Rotas recalculadas em 342 us
    (re.compile(
        r'\[ROUTING\] Rotas recalculadas em (?P<us>\d+) us'),
     "routing_recompute_us"),

    # Link quality na tabela de routing
    # [ROUTING]   ip route add 10.0.0.3 via 10.0.0.2 dev tun1  [relay via 2, quality=78]
    (re.compile(
        r'\[ROUTING\].*\[relay via (?P<relay>\d+), quality=(?P<quality>\d+)\]'),
     "route_relay"),

    # [ROUTING]   ip route add 10.0.0.3 via 10.0.0.3 dev tun1  [directo]
    (re.compile(
        r'\[ROUTING\].*ip route add (?P<dest_ip>[\d.]+) via (?P<gw_ip>[\d.]+).*\[directo\]'),
     "route_direct"),

    # Link quality da matrix (beacon recebido)
    # [MATRIX] Node 2: quality=85 (172.20.10.2)
    (re.compile(
        r'\[MATRIX\] Node (?P<node>\d+): quality=(?P<quality>\d+)'),
     "link_quality"),

    # Peer TCP perdido
    # [TCP] Peer 3 socket morto
    (re.compile(
        r'\[TCP\] Peer (?P<peer>\d+) socket morto'),
     "peer_lost"),

    # Peer TCP reconectado
    # [TCP] Conectado ao peer 3
    (re.compile(
        r'\[TCP\] Conectado ao peer (?P<peer>\d+)'),
     "peer_connected"),

    # Topologia mudou
    # [EVENT] TOPOLOGY_CHANGED
    (re.compile(
        r'\[EVENT\] TOPOLOGY_CHANGED'),
     "topology_changed"),

    # tx_queue overflow (tail drop)
    # [TX_QUEUE] FULL — a descartar pacote mais antigo
    (re.compile(
        r'\[TX_QUEUE\] FULL'),
     "queue_overflow"),

    # MST edges (link quality entre nós)
    # [MST] Edge: 1-2 cost=22 (quality=78)
    (re.compile(
        r'\[MST\] Edge: (?P<n1>\d+)-(?P<n2>\d+) cost=(?P<cost>\d+) \(quality=(?P<quality>\d+)\)'),
     "mst_edge"),
]

# ── Contadores acumulados ─────────────────────────────────────────────────────

counters = {
    "pkts_sent":       0,
    "pkts_delivered":  0,
    "pkts_relayed":    0,
    "queue_overflows": 0,
    "peer_lost":       0,
    "topology_changes": 0,
}

last_summary_t = time.time()
SUMMARY_INTERVAL = 10.0   # resumo a cada 10s

def emit(event_type, data):
    record = {
        "ts":    round(time.time(), 3),
        "event": event_type,
        **data,
    }
    line = json.dumps(record)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def print_summary():
    print(
        f"[METRICS] pkts_sent={counters['pkts_sent']} "
        f"delivered={counters['pkts_delivered']} "
        f"relayed={counters['pkts_relayed']} "
        f"drops={counters['queue_overflows']} "
        f"peer_lost={counters['peer_lost']} "
        f"topo_changes={counters['topology_changes']}",
        flush=True
    )

def handle_line(line):
    global last_summary_t

    line = line.rstrip()
    if not line:
        return

    for pattern, event_type in PATTERNS:
        m = pattern.search(line)
        if not m:
            continue

        data = m.groupdict()

        # converte strings numéricas para int
        for k, v in data.items():
            if v is not None and v.isdigit():
                data[k] = int(v)

        emit(event_type, data)

        # actualiza contadores
        if event_type == "pkt_sent":
            counters["pkts_sent"] += 1
        elif event_type == "pkt_delivered":
            counters["pkts_delivered"] += 1
        elif event_type == "pkt_relayed":
            counters["pkts_relayed"] += 1
        elif event_type == "queue_overflow":
            counters["queue_overflows"] += 1
        elif event_type == "peer_lost":
            counters["peer_lost"] += 1
        elif event_type == "topology_changed":
            counters["topology_changes"] += 1

        break   # só aplica o primeiro padrão que faz match

    now = time.time()
    if now - last_summary_t >= SUMMARY_INTERVAL:
        print_summary()
        last_summary_t = now

def main():
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    print(f"[METRICS] A escrever métricas em {LOG_FILE}", flush=True)
    for line in sys.stdin:
        handle_line(line)
    print_summary()

if __name__ == "__main__":
    main()
