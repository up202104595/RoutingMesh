#!/usr/bin/env python3
"""
convergence_test.py — Convergência do relay (método Ana), medida pela
interrupção do vídeo. Idêntico em metodologia ao teste do método Miguel, para
comparação directa.

Captura PASSIVA (AF_PACKET) na interface, em vez de ocupar a porta 5000, para
coexistir com o ffplay/base_station sem conflito de porta. O vídeo chega ao N3
sempre como UDP para a porta do framework do N3 (BASE_PORT+3 = 7003), tanto no
directo como no relay; distingue-se dos beacons pelo tamanho (>200 B).

Procedimento (corre no N3, COM SUDO, com vídeo a fluir e mesh ativa):
  1. Captura passiva dos pacotes de vídeo (UDP dport 7003, payload >200 B).
  2. (modo manual, --no-block) bloqueio aplicado A MAO no N1 quando indicado.
  3. Deteta o gap no vídeo (> GAP_THRESHOLD s sem pacotes).
  4. Regista quando o vídeo retoma via relay (N1->N2->N3).
  5. Convergência = tempo do último pkt directo até ao primeiro pkt via relay.

Uso:
    sudo python3 convergence_test.py --no-block --label conv_r1 --iface wlp5s0
    sudo python3 convergence_test.py --no-block --label conv_r1   # iface default wlp5s0
"""

import os, socket, time, json, argparse, struct

DATA_PORT      = 7003     # porta do framework do N3 (BASE_PORT + node_id)
MIN_VIDEO_SIZE = 200      # bytes UDP; separa o vídeo dos beacons (~71 B)
GAP_THRESHOLD  = 0.4
WARMUP_S       = 3.0
MAX_WAIT_S     = 30.0
ETH_P_ALL      = 0x0003


def block_link(phy):
    os.system(f"iptables -I INPUT  1 -s {phy} -j DROP")
    os.system(f"iptables -I OUTPUT 1 -d {phy} -j DROP")


def restore_link(phy):
    os.system(f"iptables -D INPUT  -s {phy} -j DROP 2>/dev/null")
    os.system(f"iptables -D OUTPUT -d {phy} -j DROP 2>/dev/null")


def open_capture(iface):
    """Socket AF_PACKET (precisa de root) ligado à interface, p/ captura passiva."""
    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ALL))
    s.bind((iface, 0))
    s.settimeout(0.05)
    return s


def is_video_frame(frame, data_port, min_size):
    """True se o frame Ethernet for um UDP para data_port com payload >= min_size."""
    if len(frame) < 14 + 20 + 8:
        return False
    if ((frame[12] << 8) | frame[13]) != 0x0800:      # EtherType IPv4
        return False
    ihl = (frame[14] & 0x0F) * 4
    if frame[14 + 9] != 17:                            # protocolo UDP
        return False
    udp = 14 + ihl
    if len(frame) < udp + 8:
        return False
    dport = (frame[udp + 2] << 8) | frame[udp + 3]
    ulen  = (frame[udp + 4] << 8) | frame[udp + 5]     # UDP length (header+payload)
    return dport == data_port and ulen >= min_size


def poll_video(sock, data_port, min_size):
    """Lê um frame; devolve True se for pacote de vídeo, False (timeout/não-vídeo)."""
    try:
        frame = sock.recv(65536)
    except socket.timeout:
        return False
    return is_video_frame(frame, data_port, min_size)


def run(label, phy, do_block=True, n3_phy="172.20.10.3",
        iface="wlp5s0", data_port=DATA_PORT):
    try:
        sock = open_capture(iface)
    except PermissionError:
        print("[CONV] ERRO: captura AF_PACKET precisa de root. Corre com sudo.")
        return {"label": label, "converged": False, "convergence_ms": None,
                "error": "needs_root"}
    except OSError as e:
        print(f"[CONV] ERRO ao abrir captura em '{iface}': {e}")
        return {"label": label, "converged": False, "convergence_ms": None,
                "error": "iface"}

    print(f"[CONV] label={label}  iface={iface}  dport={data_port}  gap={GAP_THRESHOLD}s")
    print(f"[CONV] a aguardar vídeo estável ({WARMUP_S}s)...")

    warmup_start, warmup_pkts = None, 0
    warmup_deadline = time.perf_counter() + 60.0
    while True:
        if time.perf_counter() > warmup_deadline:
            print("[CONV] timeout: sem vídeo em 60s — o vídeo está a fluir? iface certa?")
            sock.close()
            return {"label": label, "converged": False, "convergence_ms": None,
                    "error": "no_video_warmup"}
        if poll_video(sock, data_port, MIN_VIDEO_SIZE):
            now = time.perf_counter()
            if warmup_start is None:
                warmup_start = now
                print("[CONV] vídeo detectado — a estabilizar...")
            warmup_pkts += 1
            if now - warmup_start >= WARMUP_S:
                break

    print(f"[CONV] warmup OK ({warmup_pkts} pkts). "
          f"{'a bloquear link...' if do_block else 'modo monitor.'}")

    t_block = time.perf_counter()
    if do_block:
        block_link(phy)
    else:
        # Modo manual: o bloqueio TEM de ser aplicado no N1 (a Ana relaya com o
        # IP fisico do N1 intacto, por isso bloquear no N3 deitava fora o video
        # relayado). Instrucao explicita; a deteccao do gap/recuperacao e automatica.
        print("\n" + "=" * 60)
        print("  >>> AGORA aplica o bloqueio NO N1 (robot): <<<")
        print(f"      sudo iptables -I INPUT -s {n3_phy} -j DROP")
        print("  (o N1 deixa de ouvir o N3 -> re-roteia via N2)")
        print("  O teste deteta sozinho o gap e a recuperacao.")
        print("  No fim restaura no N1:")
        print(f"      sudo iptables -D INPUT -s {n3_phy} -j DROP")
        print("=" * 60 + "\n")

    last_pkt_t = time.perf_counter()
    gap_detected = False
    t_gap_start = t_converged = None
    pkts_after = []
    deadline = t_block + MAX_WAIT_S + 30

    while time.perf_counter() < deadline:
        if poll_video(sock, data_port, MIN_VIDEO_SIZE):
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
        else:
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
                    help="endereço físico do N1 (usado só no modo automático)")
    ap.add_argument("--no-block", action="store_true",
                    help="modo manual: monitoriza no N3, bloqueio aplicado a mao no N1")
    ap.add_argument("--n3-phy", default="172.20.10.3",
                    help="endereco fisico do N3 a bloquear NO N1 (default 172.20.10.3)")
    ap.add_argument("--iface", default="wlp5s0",
                    help="interface de captura do N3 (default wlp5s0)")
    ap.add_argument("--data-port", type=int, default=DATA_PORT,
                    help="porta do framework do N3 onde chega o vídeo (default 7003)")
    args = ap.parse_args()
    run(args.label, args.node1_phy, do_block=not args.no_block,
        n3_phy=args.n3_phy, iface=args.iface, data_port=args.data_port)
