#!/usr/bin/env python3
"""
servo_debug.py — Testa os servos do AlphaBot2 via smbus2
Corre na Raspberry: sudo python3 servo_debug.py
"""
import time, sys, subprocess

print("=" * 50)
print("  AlphaBot2 Servo Debug (smbus2)")
print("=" * 50)

# ── 1. i2cdetect ─────────────────────────────────────────────
print("\n[1] i2cdetect -y 1:")
r = subprocess.run(["i2cdetect", "-y", "1"], capture_output=True, text=True)
print(r.stdout)
if "40" in r.stdout:
    print("    OK: PCA9685 em 0x40")
else:
    print("    AVISO: 0x40 não encontrado — verifica ligações e alimentação")

# ── 2. smbus2 ────────────────────────────────────────────────
print("\n[2] A importar smbus2...")
try:
    import smbus2
    print("    OK")
except ImportError:
    print("    ERRO: sudo apt install python3-smbus2")
    sys.exit(1)

# ── 3. Init PCA9685 ──────────────────────────────────────────
print("\n[3] A inicializar PCA9685...")
try:
    bus = smbus2.SMBus(1)
    bus.write_byte_data(0x40, 0x00, 0x10)   # sleep
    time.sleep(0.005)
    bus.write_byte_data(0x40, 0xFE, 0x79)   # prescaler 50Hz
    time.sleep(0.005)
    bus.write_byte_data(0x40, 0x00, 0x00)   # wake
    time.sleep(0.005)
    print("    OK")
except Exception as e:
    print(f"    ERRO: {e}")
    sys.exit(1)

def set_servo(channel, degrees):
    degrees = max(0, min(500, degrees))  # range alargado para calibração
    pulse = int(102 + (degrees / 270.0) * 410)  # 0.5ms→2.5ms range completo
    reg   = 0x06 + 4 * channel
    bus.write_byte_data(0x40, reg,     0x00)
    bus.write_byte_data(0x40, reg + 1, 0x00)
    bus.write_byte_data(0x40, reg + 2, pulse & 0xFF)
    bus.write_byte_data(0x40, reg + 3, pulse >> 8)

# ── 4. Servo 0 (pan) ─────────────────────────────────────────
print("\n[4] Servo 0 (PAN):")
for deg in [90, 45, 135, 90]:
    print(f"    → {deg}°")
    set_servo(0, deg)
    time.sleep(1)

# ── 5. Servo 1 (tilt) ────────────────────────────────────────
print("\n[5] Servo 1 (TILT):")
for deg in [90, 45, 135, 90]:
    print(f"    → {deg}°")
    set_servo(1, deg)
    time.sleep(1)

# ── 6. Interativo ────────────────────────────────────────────
print("\n[6] Teste manual — formato: <servo> <graus>  ex: 0 90  (Ctrl+C sai)")
while True:
    try:
        parts = input("    > ").strip().split()
        set_servo(int(parts[0]), int(parts[1]))
        print(f"    Servo {parts[0]} → {parts[1]}°")
    except KeyboardInterrupt:
        print("\n    Saindo.")
        break
    except Exception as e:
        print(f"    ERRO: {e}")
