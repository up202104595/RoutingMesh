#!/usr/bin/env python3
"""
convergence_test.py — Convergência medida pela interrupção do vídeo

Procedimento automático:
  1. Monitoriza port 5000 (SO_REUSEPORT) — vídeo a fluir diretamente N1->N3
  2. Aplica iptables para bloquear link direto N1->N3
  3. Deteta gap no vídeo (> GAP_THRESHOLD segundos sem pacotes)
  4. Regista quando o vídeo retoma via relay (N1->N2->N3)
  5. Convergência = tempo desde último pkt direto até primeiro pkt relay

Uso (no Nó 3, com vídeo a fluir e mesh ativa):
    python3 convergence_test.py --label "conv_1"
    python3 convergence_test.py --label "conv_1" --no-block  # só monitoriza
"""

import os
import socket
import time
import json
import subprocess
import argparse
import statistics

VIDEO_PORT    = 5000
GAP_THRESHOLD = 0.4   # segundos sem pacotes -> link quebrado
WARMUP_S      = 3.0   # vídeo estável antes de bloquear
MAX_WAIT_S    = 30.0  # tempo máximo à espera de convergência


def block_link():
    os.system("iptables -I INPUT  1 -s 172.20.10.1 -j DROP")
    os.system("iptables -I OUTPUT 1 -d 172.20.10.1 -j DROP")


def restore_link():
    os.system("iptables -D INPUT  -s 172.20.10.1 -j DROP 2>/dev/null")
    os.system("iptables -D OUTPUT -d 172.20.10.1 -j DROP 2>/dev/null")


def run(label, do_block=True):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except AttributeError:
        pass
    sock.bind(("0.0.0.0", VIDEO_PORT))
    sock.settimeout(0.05)

    WARMUP_TIMEOUT = 60.0   # desiste se nenhum vídeo chegar em 60s

    print(f"[CONV] Label={label}  GAP_threshold={GAP_THRESHOLD}s")
    print(f"[CONV] A aguardar vídeo estável ({WARMUP_S}s)...")

    # ── warmup: espera vídeo estável ──────────────────────────────────────
    warmup_start  = None
    warmup_pkts   = 0
    warmup_deadline = time.perf_counter() + WARMUP_TIMEOUT
    while True:
        if time.perf_counter() > warmup_deadline:
            print(f"\n[CONV] Timeout: sem vídeo em {WARMUP_TIMEOUT:.0f}s — o vídeo está a fluir?")
            sock.close()
            return {"label": label, "converged": False, "convergence_ms": None,
                    "error": "no_video_warmup"}
        try:
            data, _ = sock.recvfrom(65536)
            now = time.perf_counter()
            if warmup_start is None:
                warmup_start = now
                print(f"[CONV] Vídeo detectado — a aguardar {WARMUP_S}s estável...")
            warmup_pkts += 1
            if now - warmup_start >= WARMUP_S:
                break
        except socket.timeout:
            pass

    print(f"[CONV] Warmup OK ({warmup_pkts} pkts).  "
          f"{'A bloquear link direto...' if do_block else 'Modo monitor (sem bloqueio).'}")

    # ── bloquear link ─────────────────────────────────────────────────────
    t_block = time.perf_counter()
    if do_block:
        block_link()
        print(f"[CONV] Link direto bloqueado")

    # ── detetar gap e convergência ────────────────────────────────────────
    last_pkt_t   = time.perf_counter()
    gap_detected = False
    t_gap_start  = None  # timestamp do último pkt antes do gap
    t_converged  = None  # timestamp do primeiro pkt após gap
    pkts_before  = []    # inter-arrival (ms) antes do gap
    pkts_after   = []    # inter-arrival (ms) após convergência
    prev_t       = None
    deadline     = t_block + MAX_WAIT_S + 10

    while time.perf_counter() < deadline:
        try:
            data, _ = sock.recvfrom(65536)
            now     = time.perf_counter()
            elapsed = now - t_block

            if not gap_detected:
                t_gap_start = now
                last_pkt_t  = now
                if prev_t:
                    pkts_before.append((now - prev_t) * 1000)
                prev_t = now
                print(f"\r[CONV] t={elapsed:5.2f}s  DIRETO              ", end="", flush=True)
            else:
                if t_converged is None:
                    t_converged = now
                    conv_ms = (t_converged - t_gap_start) * 1000
                    print(f"\n[CONV] *** CONVERGIU em {conv_ms:.0f} ms (t={elapsed:.2f}s) ***")
                if prev_t:
                    pkts_after.append((now - prev_t) * 1000)
                prev_t = now
                print(f"\r[CONV] t={elapsed:5.2f}s  RELAY  pkts={len(pkts_after):4d}  ",
                      end="", flush=True)
                if len(pkts_after) >= 50:
                    break

        except socket.timeout:
            now     = time.perf_counter()
            elapsed = now - t_block
            gap     = now - last_pkt_t

            if not gap_detected and gap > GAP_THRESHOLD:
                gap_detected = True
                print(f"\n[CONV] *** GAP DETECTADO  t={elapsed:.2f}s  gap={gap:.2f}s ***")

            if gap_detected and t_converged is None:
                print(f"\r[CONV] t={elapsed:5.2f}s  SEM VÍDEO  gap={gap:.2f}s    ",
                      end="", flush=True)
                if (now - t_block) > MAX_WAIT_S:
                    print(f"\n[CONV] Timeout — relay não convergiu em {MAX_WAIT_S}s")
                    break

    print()
    sock.close()

    if do_block:
        restore_link()
        print("[CONV] Link direto restaurado")

    conv_ms = None
    if t_gap_start and t_converged:
        conv_ms = round((t_converged - t_gap_start) * 1000, 1)

    result = {
        "label":           label,
        "timestamp":       time.strftime("%Y-%m-%dT%H:%M:%S"),
        "gap_threshold_s": GAP_THRESHOLD,
        "convergence_ms":  conv_ms,
        "converged":       t_converged is not None,
    }

    if len(pkts_before) > 1:
        result["inter_arrival_before_ms"] = {
            "avg": round(statistics.mean(pkts_before), 2),
            "std": round(statistics.stdev(pkts_before), 2),
        }
    if len(pkts_after) > 1:
        result["inter_arrival_after_ms"] = {
            "avg": round(statistics.mean(pkts_after), 2),
            "std": round(statistics.stdev(pkts_after), 2),
        }

    print(f"\n[CONV] Convergência: {conv_ms} ms" if conv_ms else "\n[CONV] Sem convergência")
    fname = f"convergence_{label}.json"
    with open(fname, "w") as f:
        json.dump(result, f, indent=2)
    print(f"[CONV] Guardado -> {fname}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--label",    default="conv_1")
    parser.add_argument("--no-block", action="store_true",
                        help="Nao aplica iptables — so monitoriza")
    args = parser.parse_args()
    run(args.label, do_block=not args.no_block)
