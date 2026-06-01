#!/usr/bin/env python3
"""
servo_debug.py — Testa os servos do AlphaBot2 passo a passo
Corre na Raspberry: sudo python3 servo_debug.py
"""

import time
import sys

print("=" * 50)
print("  AlphaBot2 Servo Debug")
print("=" * 50)

# ── 1. Verifica I2C no sistema ────────────────────────────────
print("\n[1] A verificar I2C...")
import subprocess
result = subprocess.run(["i2cdetect", "-y", "1"], capture_output=True, text=True)
if result.returncode != 0:
    print("    ERRO: i2cdetect falhou — I2C está ativo?")
    print("    Ativa com: sudo raspi-config → Interface Options → I2C → Enable")
    sys.exit(1)
print(result.stdout)
if "40" in result.stdout:
    print("    OK: PCA9685 detectado em 0x40")
else:
    print("    AVISO: 0x40 não encontrado no I2C bus!")
    print("    Verifica ligações e alimentação do servo")

# ── 2. Verifica adafruit_servokit ────────────────────────────
print("\n[2] A importar adafruit_servokit...")
try:
    from adafruit_servokit import ServoKit
    print("    OK: adafruit_servokit disponível")
except ImportError:
    print("    ERRO: adafruit_servokit não instalado")
    print("    Instala: pip3 install adafruit-circuitpython-servokit")
    sys.exit(1)

# ── 3. Inicializa ServoKit ────────────────────────────────────
print("\n[3] A inicializar ServoKit(channels=16)...")
try:
    kit = ServoKit(channels=16)
    print("    OK")
except Exception as e:
    print(f"    ERRO: {e}")
    sys.exit(1)

# ── 4. Testa servo 0 (pan) ────────────────────────────────────
print("\n[4] Servo 0 (PAN — horizontal)...")
try:
    print("    → 90° (centro)")
    kit.servo[0].angle = 90
    time.sleep(1)
    print("    → 45° (esquerda)")
    kit.servo[0].angle = 45
    time.sleep(1)
    print("    → 135° (direita)")
    kit.servo[0].angle = 135
    time.sleep(1)
    print("    → 90° (centro)")
    kit.servo[0].angle = 90
    time.sleep(1)
    print("    OK: Servo 0 respondeu")
except Exception as e:
    print(f"    ERRO servo 0: {e}")

# ── 5. Testa servo 1 (tilt) ───────────────────────────────────
print("\n[5] Servo 1 (TILT — vertical)...")
try:
    print("    → 90° (centro)")
    kit.servo[1].angle = 90
    time.sleep(1)
    print("    → 45° (cima)")
    kit.servo[1].angle = 45
    time.sleep(1)
    print("    → 135° (baixo)")
    kit.servo[1].angle = 135
    time.sleep(1)
    print("    → 90° (centro)")
    kit.servo[1].angle = 90
    time.sleep(1)
    print("    OK: Servo 1 respondeu")
except Exception as e:
    print(f"    ERRO servo 1: {e}")

# ── 6. Teste manual interativo ────────────────────────────────
print("\n[6] Teste manual (Ctrl+C para sair)")
print("    Formato: <servo> <graus>   ex: 0 90   ou   1 45")
while True:
    try:
        line = input("    > ").strip()
        if not line:
            continue
        parts = line.split()
        ch  = int(parts[0])
        deg = int(parts[1])
        kit.servo[ch].angle = max(5, min(175, deg))
        print(f"    Servo {ch} → {deg}°")
    except KeyboardInterrupt:
        print("\n    Saindo.")
        break
    except Exception as e:
        print(f"    ERRO: {e}")
