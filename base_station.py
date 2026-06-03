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
  Triangle (btn 2)   : Centrar câmara (90/90)
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
ROBOT_IP  = "10.0.0.1"
CMD_PORT  = 9000
TEL_PORT  = 9001

# ── Controlo ─────────────────────────────────────────────────
DEADZONE         = 0.1
CMD_INTERVAL     = 0.05    # 20 Hz
SERVO_INTERVAL   = 0.08    # ~12 Hz para servos

# Modos de velocidade (D-Pad L/R)
SPEED_MODES  = [0.3, 0.55, 0.8]
SPEED_LABELS = ["LENTO", "MÉDIO", "RÁPIDO"]
SERVO_STEP   = 8   # graus por press de botão

# Valores calibrados fisicamente (servo_debug.py)
SERVO_PAN_CENTER  = 100;  SERVO_PAN_MIN  =   0; SERVO_PAN_MAX  = 200
SERVO_TILT_CENTER = 420;  SERVO_TILT_MIN = 300; SERVO_TILT_MAX = 500

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

# ═════════════════════════════════════════════════════════════
# FFPLAY
# ═════════════════════════════════════════════════════════════

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
        "-i", "udp://0.0.0.0:5000",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"[VIDEO] ffplay iniciado — udp://0.0.0.0:5000 (PID {proc.pid})")
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
    threading.Thread(target=telemetry_receiver, daemon=True).start()
    threading.Thread(target=ffplay_watchdog, args=(proc_ref,), daemon=True).start()

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
    speed_idx   = 1          # começa em MÉDIO
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

            # ── PS → sair ─────────────────────────────────────
            if btn(joy, BTN_PS):
                print("\n[BASE] PS premido — a sair...")
                break

            # ── Cross → paragem de emergência ─────────────────
            if btn(joy, BTN_CROSS):
                send_cmd(sock, {"cmd": "stop"})
                print("\n[BASE] PARAGEM DE EMERGÊNCIA!")
                time.sleep(0.1)
                continue

            # ── D-Pad L/R → modo velocidade ───────────────────
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

            # ── Movimento: Left Stick — tank drive
            if now - last_move_t >= CMD_INTERVAL:
                x = apply_deadzone(axis(joy, AX_LEFT_X))
                y = apply_deadzone(axis(joy, AX_LEFT_Y))
                # y negativo = stick para cima = avançar
                left  = max(-1.0, min(1.0, -y + x)) * max_speed
                right = max(-1.0, min(1.0, -y - x)) * max_speed

                if abs(left) > 0.02 or abs(right) > 0.02:
                    send_cmd(sock, {"cmd": "move",
                                    "left":  round(left,  3),
                                    "right": round(right, 3)})
                else:
                    send_cmd(sock, {"cmd": "stop"})
                last_move_t = now

            # ── Câmara ────────────────────────────────────────
            if now - last_srv_t >= SERVO_INTERVAL:
                changed = False

                # Triangle → centrar
                if btn(joy, BTN_TRIANGLE):
                    servo_pan  = SERVO_PAN_CENTER
                    servo_tilt = SERVO_TILT_CENTER
                    changed    = True
                    print("\n[BASE] Câmara centrada")
                else:
                    # L1/R1 → pan esq/dir
                    if btn(joy, BTN_L1):
                        servo_pan = max(SERVO_PAN_MIN,  servo_pan - SERVO_STEP)
                        changed   = True
                    if btn(joy, BTN_R1):
                        servo_pan = min(SERVO_PAN_MAX,  servo_pan + SERVO_STEP)
                        changed   = True
                    # D-Pad ↑↓ → tilt (↑=mais alto=valor menor, ↓=mais baixo=valor maior)
                    dpad_y = axis(joy, AX_DPAD_Y)
                    if dpad_y < -0.5:
                        servo_tilt = max(SERVO_TILT_MIN, servo_tilt - SERVO_STEP)
                        changed    = True
                    elif dpad_y > 0.5:
                        servo_tilt = min(SERVO_TILT_MAX, servo_tilt + SERVO_STEP)
                        changed    = True

                if changed:
                    send_cmd(sock, {"cmd": "servo",
                                    "pan":  servo_pan,
                                    "tilt": servo_tilt})
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
