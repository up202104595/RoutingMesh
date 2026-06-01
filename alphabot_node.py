#!/usr/bin/env python3
"""
alphabot_node.py — AlphaBot2 Waveshare — Raspberry Pi (Nó 1)

Inicia o stream de vídeo UDP via TUN para o nó 3.
O TDMA trata do transporte e relay automaticamente.
"""

import socket
import json
import time
import threading
import subprocess

# ── GPIO ─────────────────────────────────────────────────────
try:
    import RPi.GPIO as GPIO
    HAS_GPIO = True
except ImportError:
    print("[ALPHABOT] AVISO: RPi.GPIO nao disponivel — modo simulacao")
    HAS_GPIO = False

# ── I2C / PCA9685 ────────────────────────────────────────────
try:
    import smbus2
    HAS_I2C = True
except ImportError:
    print("[ALPHABOT] AVISO: smbus2 nao instalado — servo desactivado")
    HAS_I2C = False

class PCA9685:
    def __init__(self, address=0x40, bus=1):
        self.address  = address
        self.bus_num  = bus
        self.bus      = None
        self._init_bus()

    def _init_bus(self):
        try:
            if self.bus:
                try: self.bus.close()
                except Exception: pass
            self.bus = smbus2.SMBus(self.bus_num)
            self.bus.write_byte_data(self.address, 0x00, 0x10)   # MODE1: sleep
            time.sleep(0.005)
            self.bus.write_byte_data(self.address, 0xFE, 0x79)   # prescaler → 50 Hz
            time.sleep(0.005)
            self.bus.write_byte_data(self.address, 0x00, 0x20)   # MODE1: auto-increment, wake
            time.sleep(0.005)
            print(f"[PCA9685] I2C bus {self.bus_num} addr=0x{self.address:02X} OK")
        except Exception as e:
            print(f"[PCA9685] ERRO init I2C: {e}")
            self.bus = None

    def set_servo(self, channel, degrees):
        degrees = max(0, min(180, degrees))
        # 50 Hz, 12-bit: 0°=205 (1 ms), 90°=307 (1.5 ms), 180°=410 (2 ms)
        pulse = int(205 + (degrees / 180.0) * 205)
        reg   = 0x06 + 4 * channel
        for attempt in range(2):
            try:
                if self.bus is None:
                    self._init_bus()
                if self.bus is None:
                    return
                self.bus.write_byte_data(self.address, reg,     0x00)
                self.bus.write_byte_data(self.address, reg + 1, 0x00)
                self.bus.write_byte_data(self.address, reg + 2, pulse & 0xFF)
                self.bus.write_byte_data(self.address, reg + 3, pulse >> 8)
                return
            except Exception as e:
                print(f"[PCA9685] ERRO I2C ch{channel} tentativa {attempt+1}: {e}")
                self.bus = None   # força reinit na próxima tentativa
                time.sleep(0.05)

# ── Pinos AlphaBot2-Pi (TB6612FNG) ────────────────────────────
AIN1=12; AIN2=13; BIN1=20; BIN2=21; PWMA=6; PWMB=26
TRIG=22; ECHO=27; IR_LEFT=16; IR_RIGHT=19

# ── Rede ─────────────────────────────────────────────────────
CMD_PORT           = 9000
TEL_PORT           = 9001
BASE_IP            = "10.0.0.3"
TELEMETRY_INTERVAL = 0.2

# ── Parâmetros de vídeo ───────────────────────────────────────
VIDEO_WIDTH   = 640
VIDEO_HEIGHT  = 480
VIDEO_FPS     = 15
VIDEO_BITRATE = 500000   # 500 kbps

# ── Estado global ─────────────────────────────────────────────
g_speed_l  = 0.0
g_speed_r  = 0.0
g_running  = True
g_last_cmd = time.time()
g_lock     = threading.Lock()
pwm_a = None; pwm_b = None; pca = None

# ═════════════════════════════════════════════════════════════
# STREAM — inicia uma vez, watchdog reinicia se cair
# ═════════════════════════════════════════════════════════════

def start_stream():
    cmd = (
        f"rpicam-vid -t 0 "
        f"--width {VIDEO_WIDTH} --height {VIDEO_HEIGHT} "
        f"--framerate {VIDEO_FPS} "
        f"--codec yuv420 -o - 2>/dev/null | "
        f"ffmpeg -fflags nobuffer "
        f"-f rawvideo -pix_fmt yuv420p "
        f"-s {VIDEO_WIDTH}x{VIDEO_HEIGHT} -r {VIDEO_FPS} -i - "
        f"-c:v libx264 -preset ultrafast -tune zerolatency "
        f"-g 1 -b:v {VIDEO_BITRATE} "
        f"-f mpegts "
        f'"udp://{BASE_IP}:5000?pkt_size=1316" '
        f"2>/dev/null"
    )
    proc = subprocess.Popen(cmd, shell=True,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    print(f"[VIDEO] Stream iniciado — {VIDEO_BITRATE//1000}kbps "
          f"{VIDEO_WIDTH}x{VIDEO_HEIGHT}@{VIDEO_FPS}fps (PID {proc.pid})")
    return proc

def stop_stream(proc):
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
    subprocess.run(["pkill", "-f", "rpicam-vid"], capture_output=True)
    subprocess.run(["pkill", "-f", "ffmpeg"],     capture_output=True)

def stream_watchdog(proc_ref):
    """Reinicia o stream se rpicam-vid/ffmpeg terminarem inesperadamente."""
    while g_running:
        time.sleep(5)
        if not g_running:
            break
        proc = proc_ref[0]
        if proc is not None and proc.poll() is not None:
            print("[VIDEO] Stream caiu — a reiniciar em 2s...")
            stop_stream(proc)
            time.sleep(2)
            if g_running:
                proc_ref[0] = start_stream()

# ═════════════════════════════════════════════════════════════
# HARDWARE
# ═════════════════════════════════════════════════════════════

def hardware_init():
    global pwm_a, pwm_b, pca
    if HAS_GPIO:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        for pin in [AIN1, AIN2, BIN1, BIN2, PWMA, PWMB]:
            GPIO.setup(pin, GPIO.OUT)
            GPIO.output(pin, GPIO.LOW)
        pwm_a = GPIO.PWM(PWMA, 500)
        pwm_b = GPIO.PWM(PWMB, 500)
        pwm_a.start(0)
        pwm_b.start(0)
        GPIO.setup(TRIG, GPIO.OUT)
        GPIO.setup(ECHO, GPIO.IN)
        GPIO.output(TRIG, GPIO.LOW)
        GPIO.setup(IR_LEFT,  GPIO.IN)
        GPIO.setup(IR_RIGHT, GPIO.IN)
        print("[ALPHABOT] GPIO inicializado")
    if HAS_I2C:
        try:
            pca = PCA9685(0x40, 1)
            pca.set_servo(0, 90)   # pan centrado
            pca.set_servo(1, 90)   # tilt centrado
            print("[ALPHABOT] Servos centrados (90°)")
        except Exception as e:
            print(f"[ALPHABOT] ERRO PCA9685: {e}")
            pca = None

def hardware_cleanup():
    if HAS_GPIO:
        motors_stop()
        if pwm_a: pwm_a.stop()
        if pwm_b: pwm_b.stop()
        GPIO.cleanup()

def motor_set(speed_l, speed_r):
    global g_speed_l, g_speed_r

    # BUG FIX: clampagem ANTES de usar os valores — o código original
    # clampava apenas g_speed_l/r (para telemetria) mas usava os valores
    # originais não clampados para o PWM, podendo gerar duty_cycle > 100%
    speed_l = max(-1.0, min(1.0, speed_l))
    speed_r = max(-1.0, min(1.0, speed_r))

    with g_lock:
        g_speed_l = speed_l
        g_speed_r = speed_r

    if not HAS_GPIO:
        return

    # Motor esquerdo (Motor A: AIN1/AIN2/PWMA)
    duty_a = abs(speed_l) * 100
    if speed_l > 0:
        GPIO.output(AIN1, GPIO.HIGH)
        GPIO.output(AIN2, GPIO.LOW)
    elif speed_l < 0:
        GPIO.output(AIN1, GPIO.LOW)
        GPIO.output(AIN2, GPIO.HIGH)
    else:
        # BUG FIX: brake (ambos HIGH) em vez de coast (ambos LOW)
        # O TB6612FNG com AIN1=AIN2=HIGH activa travagem activa,
        # evitando que o robot deslize ao parar
        GPIO.output(AIN1, GPIO.HIGH)
        GPIO.output(AIN2, GPIO.HIGH)
    pwm_a.ChangeDutyCycle(duty_a)

    # Motor direito (Motor B: BIN1/BIN2/PWMB)
    duty_b = abs(speed_r) * 100
    if speed_r > 0:
        GPIO.output(BIN1, GPIO.HIGH)
        GPIO.output(BIN2, GPIO.LOW)
    elif speed_r < 0:
        GPIO.output(BIN1, GPIO.LOW)
        GPIO.output(BIN2, GPIO.HIGH)
    else:
        GPIO.output(BIN1, GPIO.HIGH)
        GPIO.output(BIN2, GPIO.HIGH)
    pwm_b.ChangeDutyCycle(duty_b)

def motors_stop():
    motor_set(0.0, 0.0)

def servo_set_pan(degrees):
    if pca:
        try:
            pca.set_servo(0, max(0, min(180, degrees)))
        except Exception as e:
            print(f"[SERVO] ERRO pan: {e}")

def servo_set_tilt(degrees):
    if pca:
        try:
            pca.set_servo(1, max(0, min(180, degrees)))
        except Exception as e:
            print(f"[SERVO] ERRO tilt: {e}")

def read_distance_cm():
    if not HAS_GPIO:
        return 99.9
    GPIO.output(TRIG, GPIO.LOW)
    time.sleep(0.002)
    GPIO.output(TRIG, GPIO.HIGH)
    time.sleep(0.00001)
    GPIO.output(TRIG, GPIO.LOW)
    timeout = time.time() + 0.03
    pulse_start = time.time()
    while GPIO.input(ECHO) == 0:
        pulse_start = time.time()
        if time.time() > timeout:
            return -1.0
    timeout = time.time() + 0.03
    pulse_end = time.time()
    while GPIO.input(ECHO) == 1:
        pulse_end = time.time()
        if time.time() > timeout:
            return -1.0
    return round((pulse_end - pulse_start) * 17150, 1)

def read_ir():
    if not HAS_GPIO:
        return 1, 1
    return GPIO.input(IR_LEFT), GPIO.input(IR_RIGHT)

# ═════════════════════════════════════════════════════════════
# THREADS
# ═════════════════════════════════════════════════════════════

def cmd_receiver():
    global g_last_cmd
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", CMD_PORT))
    sock.settimeout(0.5)
    print(f"[CMD] A ouvir comandos na porta {CMD_PORT}")
    while g_running:
        try:
            data, addr = sock.recvfrom(1024)
            msg = json.loads(data.decode())
            with g_lock:
                g_last_cmd = time.time()
            cmd = msg.get("cmd", "")
            if   cmd == "move":
                motor_set(float(msg.get("left", 0)), float(msg.get("right", 0)))
            elif cmd == "stop":
                motors_stop()
            elif cmd == "servo":
                if "pan"  in msg: servo_set_pan (int(msg["pan"]))
                if "tilt" in msg: servo_set_tilt(int(msg["tilt"]))
            else:
                print(f"[CMD] Comando desconhecido: {cmd!r} de {addr}")
        except socket.timeout:
            pass
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            print(f"[CMD] Pacote inválido: {e}")
        except Exception as e:
            print(f"[CMD] ERRO inesperado: {e}")
    sock.close()
    print("[CMD] Thread terminada")


def telemetry_sender():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    while g_running:
        try:
            d = read_distance_cm()
            il, ir = read_ir()
            with g_lock:
                sl, sr = g_speed_l, g_speed_r
            payload = json.dumps({
                "distance_cm": d,
                "ir_left":     il,
                "ir_right":    ir,
                "speed_l":     round(sl, 2),
                "speed_r":     round(sr, 2),
                "timestamp":   time.time(),
            }).encode()
            sock.sendto(payload, (BASE_IP, TEL_PORT))
        except Exception as e:
            print(f"[TEL] ERRO: {e}")
        time.sleep(TELEMETRY_INTERVAL)
    sock.close()

# ═════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════

def main():
    global g_running
    print("╔══════════════════════════════════════╗")
    print("║  AlphaBot2 — Nó 1 — RA-TDMAs+       ║")
    print("╚══════════════════════════════════════╝")
    print(f"  Stream: udp://{BASE_IP}:5000")
    print(f"  Video:  {VIDEO_WIDTH}x{VIDEO_HEIGHT}@{VIDEO_FPS}fps {VIDEO_BITRATE//1000}kbps")
    print()

    hardware_init()

    print("[ALPHABOT] A aguardar 3s para o meshnode estabilizar...")
    time.sleep(3)

    proc_ref = [start_stream()]

    threading.Thread(target=cmd_receiver,               daemon=True).start()
    threading.Thread(target=telemetry_sender,           daemon=True).start()
    threading.Thread(target=stream_watchdog,
                     args=(proc_ref,),                  daemon=True).start()

    print("[ALPHABOT] Pronto. Ctrl+C para parar.\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[ALPHABOT] A parar...")

    g_running = False
    motors_stop()
    stop_stream(proc_ref[0])
    hardware_cleanup()
    print("[ALPHABOT] Parado.")

if __name__ == "__main__":
    main()
