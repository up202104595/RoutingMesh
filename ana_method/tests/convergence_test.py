#!/usr/bin/env python3
"""
convergence_test.py — Convergência do relay (método Ana), medida pela
interrupção do vídeo. Idêntico em metodologia ao teste do método Miguel, para
comparação directa.

Procedimento automático (corre no N3, com vídeo a fluir e mesh ativa):
  1. Monitoriza a porta 5000 (vídeo N1->N3) com SO_REUSEPORT.
  2. Aplica iptables para bloquear o link direto N1->N3 (endereço físico do N1).
  3. Deteta o gap no vídeo (> GAP_THRESHOLD s sem pacotes).
  4. Regista quando o vídeo retoma via relay (N1->N2->N3).
  5. Convergência = tempo do último pkt direto até ao primeiro pkt via relay.

Uso:
    python3 convergence_test.py --label conv_r1
    python3 convergence_test.py --label conv_r1 --node1-phy 172.20.10.1
    python3 convergence_test.py --label conv_r1 --no-block   # só monitoriza
"""

import os, socket, time, json, argparse, statistics

VIDEO_PORT    = 5000
GAP_THRESHOLD = 0.4
WARMUP_S      = 3.0
MAX_WAIT_S    = 30.0


def block_link(phy):
    os.system(f"iptables -I INPUT  1 -s {phy} -j DROP")
    os.system(f"iptables -I OUTPUT 1 -d {phy} -j DROP")


def restore_link(phy):
    os.system(f"iptables -D INPUT  -s {phy} -j DROP 2>/dev/null")
    os.system(f"iptables -D OUTPUT -d {phy} -j DROP 2>/dev/null")


def run(label, phy, do_block=True):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except AttributeError:
        pass
    sock.bind(("0.0.0.0", VIDEO_PORT))
    sock.settimeout(0.05)

    print(f"[CONV] label={label}  node1_phy={phy}  gap={GAP_THRESHOLD}s")
    print(f"[CONV] a aguardar vídeo estável ({WARMUP_S}s)...")

    warmup_start, warmup_pkts = None, 0
    warmup_deadline = time.perf_counter() + 60.0
    while True:
        if time.perf_counter() > warmup_deadline:
            print("[CONV] timeout: sem vídeo em 60s — o vídeo está a fluir?")
            sock.close()
            return {"label": label, "converged": False, "convergence_ms": None,
                    "error": "no_video_warmup"}
        try:
            sock.recvfrom(65536)
            now = time.perf_counter()
            if warmup_start is None:
                warmup_start = now
                print("[CONV] vídeo detectado — a estabilizar...")
            warmup_pkts += 1
            if now - warmup_start >= WARMUP_S:
                break
        except socket.timeout:
            pass

    print(f"[CONV] warmup OK ({warmup_pkts} pkts). "
          f"{'a bloquear link...' if do_block else 'modo monitor.'}")

    t_block = time.perf_counter()
    if do_block:
        block_link(phy)

    last_pkt_t = time.perf_counter()
    gap_detected = False
    t_gap_start = t_converged = None
    pkts_after = []
    deadline = t_block + MAX_WAIT_S + 10

    while time.perf_counter() < deadline:
        try:
            sock.recvfrom(65536)
            now = time.perf_counter()
            if not gap_detected:
                t_gap_start = last_pkt_t = now
            else:
                if t_converged is None:
                    t_converged = now
                    print(f"\n[CONV] *** CONVERGIU em "
                          f"{(t_converged - t_gap_start)*1000:.0f} ms ***")
                pkts_after.append(now)
                if len(pkts_after) >= 50:
                    break
        except socket.timeout:
            now = time.perf_counter()
            gap = now - last_pkt_t
            if not gap_detected and gap > GAP_THRESHOLD:
                gap_detected = True
                print(f"\n[CONV] *** GAP detectado (gap={gap:.2f}s) ***")
            if gap_detected and t_converged is None and (now - t_block) > MAX_WAIT_S:
                print(f"\n[CONV] timeout — relay não convergiu em {MAX_WAIT_S}s")
                break

    sock.close()
    if do_block:
        restore_link(phy)
        print("[CONV] link restaurado")

    conv_ms = round((t_converged - t_gap_start) * 1000, 1) if (t_gap_start and t_converged) else None
    result = {
        "label": label, "method": "ana", "node1_phy": phy,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "gap_threshold_s": GAP_THRESHOLD,
        "convergence_ms": conv_ms,
        "converged": t_converged is not None,
    }
    print(f"[CONV] convergência: {conv_ms} ms" if conv_ms else "[CONV] sem convergência")
    fname = f"convergence_{label}.json"
    with open(fname, "w") as f:
        json.dump(result, f, indent=2)
    print(f"[CONV] guardado -> {fname}")
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="conv_r1")
    ap.add_argument("--node1-phy", default="172.20.10.1",
                    help="endereço físico do N1 a bloquear (default 172.20.10.1)")
    ap.add_argument("--no-block", action="store_true")
    args = ap.parse_args()
    run(args.label, args.node1_phy, do_block=not args.no_block)
