#!/usr/bin/env python3
"""
base_station.py — Base Station — PC (Nó 3)

Inicia o ffplay em UDP para receber o stream de vídeo.
O TDMA entrega os pacotes automaticamente via TUN ou relay.
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

# ── Joystick ─────────────────────────────────────────────────
DEADZONE         = 0.1
MAX_SPEED        = 0.8
CMD_INTERVAL     = 0.05
SERVO_INTERVAL_S = 0.10

# ── Estado global ─────────────────────────────────────────────
g_telemetry = {}
g_running   = True
g_lock      = threading.Lock()

# ═════════════════════════════════════════════════════════════
# FFPLAY — inicia uma vez, watchdog reinicia se cair
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
    proc = subprocess.Popen(cmd,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
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
    """Reinicia o ffplay se terminar inesperadamente."""
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

def joystick_to_motors(x, y):
    if abs(x) < DEADZONE: x = 0.0
    if abs(y) < DEADZONE: y = 0.0
    fwd = -y   # eixo Y do joystick: cima = -1, logo fwd = +1
    # BUG FIX: clampagem dentro de [-1, 1] ANTES de aplicar MAX_SPEED
    # O original clampava DEPOIS da multiplicação; com MAX_SPEED > 1 ou
    # entradas fora de range isso podia produzir valores intermédios errados
    left  = max(-1.0, min(1.0, fwd - x))
    right = max(-1.0, min(1.0, fwd + x))
    return left * MAX_SPEED, right * MAX_SPEED

def print_telemetry():
    with g_lock:
        tel = dict(g_telemetry)

    # BUG FIX CRÍTICO: o código original era:
    #   if not tel: print(...); return
    # Em Python o semicolon separa statements — o `return` era SEMPRE
    # executado, tornando impossível chegar ao código de telemetria abaixo.
    if not tel:
        print("[BASE] Sem telemetria...", end='\r', flush=True)
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
        f"IR:[{'OK' if il   == 1 else 'OBS'}|"
           f"{'OK' if ir_r == 1 else 'OBS'}]  "
        f"Speed:[L={sl:+.2f} R={sr:+.2f}]  "
        f"Lag:{age*1000:.0f}ms    ",
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
    print(f"  Video:  udp://0.0.0.0:5000 (setpts=0)")
    print()

    if not HAS_PYGAME:
        print("[BASE] Instala pygame: pip install pygame")
        sys.exit(1)

    proc_ref = [start_ffplay()]
    threading.Thread(target=telemetry_receiver,         daemon=True).start()
    threading.Thread(target=ffplay_watchdog,
                     args=(proc_ref,),                  daemon=True).start()

    pygame.init()
    pygame.joystick.init()
    if pygame.joystick.get_count() == 0:
        print("[BASE] ERRO: Nenhum joystick detectado!")
        stop_ffplay(proc_ref[0])
        sys.exit(1)

    joy = pygame.joystick.Joystick(0)
    joy.init()
    print(f"[BASE] Comando: {joy.get_name()}")
    print("  Analógico Esq: Movimentação")
    print("  Botão 0 (X/A): STOP Emergência")
    print("  L1/R1:         Servo esq/dir")
    print()

    sock         = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    servo_pan    = 90
    last_move_t  = 0.0
    last_servo_t = 0.0

    print("[BASE] Pronto. Ctrl+C para encerrar.\n")
    try:
        while g_running:
            pygame.event.pump()
            now = time.time()

            x = joy.get_axis(0) if joy.get_numaxes() > 0 else 0.0
            y = joy.get_axis(1) if joy.get_numaxes() > 1 else 0.0
            left, right = joystick_to_motors(x, y)

            # Botão 0 — paragem de emergência
            if joy.get_numbuttons() > 0 and joy.get_button(0):
                send_cmd(sock, {"cmd": "stop"})
                print("\n[BASE] PARAGEM DE EMERGÊNCIA!")
                time.sleep(0.1)
                continue

            # Servo — L1 (botão 4) / R1 (botão 5)
            if now - last_servo_t >= SERVO_INTERVAL_S:
                changed = False
                if joy.get_numbuttons() > 4 and joy.get_button(4):
                    servo_pan = max(0, servo_pan - 5)
                    changed   = True
                if joy.get_numbuttons() > 5 and joy.get_button(5):
                    servo_pan = min(180, servo_pan + 5)
                    changed   = True
                if changed:
                    send_cmd(sock, {"cmd": "servo", "pan": servo_pan})
                    last_servo_t = now

            # Movimento
            if now - last_move_t >= CMD_INTERVAL:
                if abs(left) > 0.02 or abs(right) > 0.02:
                    send_cmd(sock, {"cmd": "move",
                                    "left":  round(left,  3),
                                    "right": round(right, 3)})
                else:
                    send_cmd(sock, {"cmd": "stop"})
                last_move_t = now

            print_telemetry()
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
