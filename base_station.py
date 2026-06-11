#!/usr/bin/env python3
"""
base_station.py — Base Station — PC (Nó 3)

DS4 via USB — mapeamento:
  R2 (axis 5)        : Avançar
  L2 (axis 2)        : Recuar
  Right Stick X (ax3): Esterçar esq/dir
  L1 (btn 4)         : Câmara pan ← esquerda
  R1 (btn 5)         : Câmara pan → direita
  D-Pad Up   (ax7<0) : Câmara tilt ↑ cima
  D-Pad Down (ax7>0) : Câmara tilt ↓ baixo
  Triangle (btn 2)   : Centrar câmara (100/90)
  Cross    (btn 0)   : STOP emergência
  D-Pad L/R (ax6)    : Mudar modo velocidade (Lento/Médio/Rápido)
  PS       (btn 10)  : Sair
"""

import socket
import json
import time
import threading
import sys
import subprocess

try:
    import pygame
    HAS_PYGAME = True
except ImportError:
    print("[BASE] AVISO: pygame nao instalado")
    HAS_PYGAME = False

# ── Rede ─────────────────────────────────────────────────────
ROBOT_IP      = "10.0.0.1"
CMD_PORT      = 9000
TEL_PORT      = 9001
FEEDBACK_PORT = 9002   # porta de feedback de qualidade de video no Nó 1

# ── Video feedback ────────────────────────────────────────────
VIDEO_PORT          = 5000
VIDEO_LOSS_TIMEOUT   = 1.5   # segundos sem pacotes → link fraco
VIDEO_OK_STABLE      = 3.0   # segundos de video estável → link bom
FEEDBACK_INTERVAL    = 0.5   # envia feedback a cada 0.5s enquanto video falha

# ── Controlo ─────────────────────────────────────────────────
DEADZONE         = 0.1
CMD_INTERVAL     = 0.05    # 20 Hz
SERVO_INTERVAL   = 0.08    # ~12 Hz para servos

# Modos de velocidade (D-Pad L/R)
SPEED_MODES  = [0.3, 0.55, 0.8]
SPEED_LABELS = ["LENTO", "MÉDIO", "RÁPIDO"]
SERVO_STEP   = 4   # graus por press de botão

# Posições de centro calibradas fisicamente
SERVO_PAN_CENTER  = 100   # pan: 100° = frente
SERVO_TILT_CENTER = 90    # tilt: 90° = horizontal

# DS4 via USB — eixos
AX_LEFT_X  = 0
AX_LEFT_Y  = 1
AX_L2      = 2   # -1 (solto) → +1 (fundo)
AX_RIGHT_X = 3
AX_RIGHT_Y = 4
AX_R2      = 5   # -1 (solto) → +1 (fundo)
AX_DPAD_X  = 6   # -1=esq, +1=dir
AX_DPAD_Y  = 7   # -1=cima, +1=baixo

# DS4 via USB — botões
BTN_CROSS     = 0
BTN_CIRCLE    = 1
BTN_TRIANGLE  = 2
BTN_SQUARE    = 3
BTN_L1        = 4
BTN_R1        = 5
BTN_L2_BTN   = 6
BTN_R2_BTN   = 7
BTN_SHARE     = 8
BTN_OPTIONS   = 9
BTN_PS        = 10
BTN_L3        = 11
BTN_R3        = 12

# ── Estado global ─────────────────────────────────────────────
g_telemetry = {}
g_running   = True
g_lock      = threading.Lock()

# throughput stats — actualizados por video_monitor()
g_video_stats = {
    "rx_pkts":  0,
    "rx_bytes": 0,
    "t_start":  0.0,
    "window_pkts":  0,
    "window_bytes": 0,
    "window_start": 0.0,
}

# ═════════════════════════════════════════════════════════════
# FFPLAY
# ═════════════════════════════════════════════════════════════

VIDEO_LOCAL_PORT = 5001   # ffplay escuta aqui; Python faz proxy de 5000→5001

def start_ffplay():
    cmd = [
        "ffplay",
        "-fflags", "nobuffer+discardcorrupt",
        "-flags",  "low_delay",
        "-framedrop",
        "-an",
        "-vf", "setpts=0",
        "-probesize",       "32",
        "-analyzeduration", "0",
        "-i", f"udp://127.0.0.1:{VIDEO_LOCAL_PORT}",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"[VIDEO] ffplay iniciado — udp://127.0.0.1:{VIDEO_LOCAL_PORT} (PID {proc.pid})")
    return proc

def stop_ffplay(proc):
    subprocess.run(["pkill", "-f", "ffplay"], capture_output=True)
    if proc:
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            proc.kill()

def ffplay_watchdog(proc_ref):
    while g_running:
        time.sleep(5)
        if not g_running:
            break
        proc = proc_ref[0]
        if proc is not None and proc.poll() is not None:
            print("[VIDEO] ffplay caiu — a reiniciar em 2s...")
            stop_ffplay(proc)
            time.sleep(2)
            if g_running:
                proc_ref[0] = start_ffplay()

# ═════════════════════════════════════════════════════════════
# VIDEO FEEDBACK — monitoriza recepção de video e avisa Nó 1
# ═════════════════════════════════════════════════════════════

g_last_video_pkt = 0.0
g_video_poor     = False

def video_monitor():
    """
    Proxy UDP: recebe todos os pacotes de video na porta 5000,
    reencaminha intactos para ffplay em 127.0.0.1:5001,
    e regista o timestamp do último pacote recebido.
    Sem SO_REUSEPORT — ffplay não toca na porta 5000.
    """
    global g_last_video_pkt
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    rx.bind(("0.0.0.0", VIDEO_PORT))
    rx.settimeout(0.5)

    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    with g_lock:
        g_video_stats["t_start"]      = time.time()
        g_video_stats["window_start"] = time.time()

    while g_running:
        try:
            data = rx.recv(65536)
            now  = time.time()
            g_last_video_pkt = now
            tx.sendto(data, ("127.0.0.1", VIDEO_LOCAL_PORT))
            with g_lock:
                g_video_stats["rx_pkts"]      += 1
                g_video_stats["rx_bytes"]     += len(data)
                g_video_stats["window_pkts"]  += 1
                g_video_stats["window_bytes"] += len(data)
        except socket.timeout:
            pass
        except Exception:
            pass
    rx.close()
    tx.close()

def video_feedback_sender():
    """Envia feedback ao Nó 1 quando o video falha."""
    global g_video_poor
    fb_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    last_fb = 0.0
    while g_running:
        time.sleep(0.1)
        now      = time.time()
        age      = now - g_last_video_pkt if g_last_video_pkt > 0 else 0
        is_poor  = g_last_video_pkt > 0 and age > VIDEO_LOSS_TIMEOUT

        if is_poor and now - last_fb >= FEEDBACK_INTERVAL:
            try:
                msg = json.dumps({"cmd": "video_poor", "age": round(age, 2)}).encode()
                fb_sock.sendto(msg, (ROBOT_IP, FEEDBACK_PORT))
                if not g_video_poor:
                    print(f"\n[FEEDBACK] Video perdido ({age:.1f}s) — a avisar Nó 1")
                    g_video_poor = True
                last_fb = now
            except Exception:
                pass
        elif not is_poor and g_video_poor:
            print("\n[FEEDBACK] Video recuperado")
            g_video_poor = False
    fb_sock.close()

# ═════════════════════════════════════════════════════════════
# TELEMETRIA
# ═════════════════════════════════════════════════════════════

def telemetry_receiver():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", TEL_PORT))
    sock.settimeout(0.5)
    while g_running:
        try:
            data, _ = sock.recvfrom(1024)
            with g_lock:
                g_telemetry.update(json.loads(data.decode()))
        except socket.timeout:
            pass
        except Exception:
            pass
    sock.close()

def send_cmd(sock, cmd_dict):
    try:
        sock.sendto(json.dumps(cmd_dict).encode(), (ROBOT_IP, CMD_PORT))
    except Exception:
        pass

def axis(joy, idx):
    return joy.get_axis(idx) if joy.get_numaxes() > idx else 0.0

def btn(joy, idx):
    return joy.get_numbuttons() > idx and joy.get_button(idx)

def trigger_to_speed(raw):
    """Converte trigger DS4 (-1..+1) para 0..1."""
    return max(0.0, (raw + 1.0) / 2.0)

def apply_deadzone(v):
    return 0.0 if abs(v) < DEADZONE else v

def print_telemetry(speed_label):
    with g_lock:
        tel = dict(g_telemetry)
    if not tel:
        print(f"\r[BASE] Sem telemetria... [{speed_label}]          ", end='', flush=True)
        return
    age  = time.time() - tel.get("timestamp", 0)
    dist = tel.get("distance_cm", -1.0)
    il   = tel.get("ir_left",  "?")
    ir_r = tel.get("ir_right", "?")
    sl   = tel.get("speed_l",  0.0)
    sr   = tel.get("speed_r",  0.0)
    alert = "⚠  " if isinstance(dist, (int, float)) and 0 < dist < 15 else "   "
    print(
        f"\r[ROBOT]{alert}"
        f"Dist:{dist:5.1f}cm  "
        f"IR:[{'OK' if il==1 else 'OBS'}|{'OK' if ir_r==1 else 'OBS'}]  "
        f"Speed:[L={sl:+.2f} R={sr:+.2f}]  "
        f"Lag:{age*1000:.0f}ms  [{speed_label}]    ",
        end='', flush=True
    )

# ═════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════

def main():
    global g_running
    print("╔══════════════════════════════════════════╗")
    print("║  Base Station — Nó 3 — RA-TDMAs+        ║")
    print("╚══════════════════════════════════════════╝")
    print(f"  Robot:  {ROBOT_IP}:{CMD_PORT}")
    print(f"  Video:  udp://0.0.0.0:5000")
    print()

    if not HAS_PYGAME:
        print("[BASE] Instala pygame: pip install pygame")
        sys.exit(1)

    proc_ref = [start_ffplay()]
    threading.Thread(target=telemetry_receiver,    daemon=True).start()
    threading.Thread(target=ffplay_watchdog,        args=(proc_ref,), daemon=True).start()
    threading.Thread(target=video_monitor,          daemon=True).start()
    threading.Thread(target=video_feedback_sender,  daemon=True).start()

    pygame.init()
    pygame.joystick.init()
    if pygame.joystick.get_count() == 0:
        print("[BASE] ERRO: Nenhum joystick detectado!")
        stop_ffplay(proc_ref[0])
        sys.exit(1)

    joy = pygame.joystick.Joystick(0)
    joy.init()
    print(f"[BASE] Comando: {joy.get_name()}")
    print()
    print("  R2               : Avançar")
    print("  L2               : Recuar")
    print("  Right Stick X    : Esterçar esq/dir")
    print("  L1 / R1          : Câmara pan ← →")
    print("  D-Pad ↑↓         : Câmara tilt ↑↓")
    print("  Triangle (btn 2) : Centrar câmara")
    print("  Cross    (btn 0) : STOP emergência")
    print("  D-Pad ←→         : Velocidade -/+")
    print("  PS       (btn 10): Sair")
    print()

    sock        = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    servo_pan   = SERVO_PAN_CENTER
    servo_tilt  = SERVO_TILT_CENTER
    speed_idx   = 1
    last_move_t = 0.0
    last_srv_t  = 0.0
    last_dpad_t = 0.0
    dpad_x_prev = 0.0

    print(f"[BASE] Pronto. Velocidade: {SPEED_LABELS[speed_idx]}\n")
    try:
        while g_running:
            pygame.event.pump()
            now = time.time()
            max_speed = SPEED_MODES[speed_idx]

            if btn(joy, BTN_PS):
                print("\n[BASE] PS premido — a sair...")
                break

            if btn(joy, BTN_CROSS):
                send_cmd(sock, {"cmd": "stop"})
                print("\n[BASE] PARAGEM DE EMERGÊNCIA!")
                time.sleep(0.1)
                continue

            dpad_x = axis(joy, AX_DPAD_X)
            if now - last_dpad_t > 0.3 and dpad_x != dpad_x_prev:
                if dpad_x > 0.5 and speed_idx < len(SPEED_MODES) - 1:
                    speed_idx += 1
                    print(f"\n[BASE] Velocidade: {SPEED_LABELS[speed_idx]}")
                    last_dpad_t = now
                elif dpad_x < -0.5 and speed_idx > 0:
                    speed_idx -= 1
                    print(f"\n[BASE] Velocidade: {SPEED_LABELS[speed_idx]}")
                    last_dpad_t = now
                dpad_x_prev = dpad_x

            if now - last_move_t >= CMD_INTERVAL:
                fwd   = trigger_to_speed(axis(joy, AX_R2))
                bwd   = trigger_to_speed(axis(joy, AX_L2))
                net   = fwd - bwd
                steer = apply_deadzone(axis(joy, AX_RIGHT_X))

                left  = max(-1.0, min(1.0, net - steer)) * max_speed
                right = max(-1.0, min(1.0, net + steer)) * max_speed

                if abs(left) > 0.02 or abs(right) > 0.02:
                    send_cmd(sock, {"cmd": "move",
                                    "left":  round(left,  3),
                                    "right": round(right, 3)})
                else:
                    send_cmd(sock, {"cmd": "stop"})
                last_move_t = now

            if now - last_srv_t >= SERVO_INTERVAL:
                changed = False

                if btn(joy, BTN_TRIANGLE):
                    servo_pan = SERVO_PAN_CENTER
                    changed   = True
                    print("\n[BASE] Câmara pan centrada")
                else:
                    if btn(joy, BTN_L1):
                        servo_pan = max(5,   servo_pan - SERVO_STEP)
                        changed   = True
                    if btn(joy, BTN_R1):
                        servo_pan = min(175, servo_pan + SERVO_STEP)
                        changed   = True

                if changed:
                    send_cmd(sock, {"cmd": "servo", "pan": servo_pan})
                    last_srv_t = now

            print_telemetry(SPEED_LABELS[speed_idx])
            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\n\n[BASE] Encerrando...")

    send_cmd(sock, {"cmd": "stop"})
    g_running = False
    stop_ffplay(proc_ref[0])
    pygame.quit()
    sock.close()
    print("[BASE] Encerrado.")

if __name__ == "__main__":
    main()
