#!/usr/bin/env python3
"""
fwd_monitor.py — Conta pacotes reencaminhados pelo kernel (ip_forward) por segundo.

NÃO precisa de tcpdump/tshark/scapy. Lê o contador IpForwDatagrams do
/proc/net/snmp — o número de pacotes que o kernel ENCAMINHOU (ip_forward),
ou seja, que passaram pelo relay SEM passar pela aplicação/TDMA.

COMO USAR (correr no NÓ RELAY, o N2):
    python3 tests/fwd_monitor.py

  e, noutro terminal / a partir do N3, fazer os testes um de cada vez:

  1) Vídeo via relay   → deves ver ~50-65 forwards/s   (o stream de vídeo)
  2) RTT via relay      → deves ver ~15-25 forwards/s   (100 req + 100 resp)
  3) Parado             → 0 forwards/s

INTERPRETAÇÃO:
  - Se o RTT relay TAMBÉM contar forwards (>0/s) no N2  → o RTT faz o MESMO
    caminho ip_forward que o vídeo (bypassa o TDMA). Logo o overhead de RTT
    NÃO vem de slots TDMA duplicados — vem de timing/CSMA.
  - Se o RTT relay der 0 forwards/s  → o RTT NÃO é ip_forwarded; vai por TDMA
    (re-agendado no slot do N2) e aí sim os slots extra explicam o RTT maior.
"""

import time
import sys


def read_fwd_datagrams():
    """Lê IpForwDatagrams do /proc/net/snmp (pacotes reencaminhados pelo kernel)."""
    with open('/proc/net/snmp') as f:
        lines = f.read().splitlines()
    for i, line in enumerate(lines):
        if line.startswith('Ip:') and 'Forwarding' in line:
            keys = line.split()[1:]
            vals = [int(x) for x in lines[i + 1].split()[1:]]
            return dict(zip(keys, vals)).get('ForwDatagrams', 0)
    raise RuntimeError("Não encontrei a linha 'Ip:' em /proc/net/snmp")


def read_ip_forward_flag():
    try:
        with open('/proc/sys/net/ipv4/ip_forward') as f:
            return f.read().strip()
    except OSError:
        return '?'


def main():
    flag = read_ip_forward_flag()
    print(f"[fwd_monitor] ip_forward = {flag}  (1 = encaminhamento kernel ativo)")
    if flag == '0':
        print("[fwd_monitor] AVISO: ip_forward está DESLIGADO — não haverá relay por kernel.")
    print("[fwd_monitor] A contar pacotes reencaminhados pelo kernel. Ctrl-C para parar.\n")
    print(f"  {'tempo':>8}  {'forwards/s':>11}   {'total':>10}")
    print("  " + "─" * 36)

    try:
        prev = read_fwd_datagrams()
        t0 = time.time()
        while True:
            time.sleep(1.0)
            cur = read_fwd_datagrams()
            rate = cur - prev
            bar = '█' * min(rate, 60)
            print(f"  {time.time() - t0:>7.0f}s  {rate:>11}   {cur:>10}  {bar}")
            prev = cur
    except KeyboardInterrupt:
        print("\n[fwd_monitor] Terminado.")
        sys.exit(0)


if __name__ == '__main__':
    main()
