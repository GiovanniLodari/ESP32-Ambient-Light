# =============================================================================
# test_arcobaleno.py
# Fa scorrere la striscia attraverso tutta la gamma cromatica HSV,
# con transizioni morbide tra un colore e l'altro.
# Ctrl+C per fermare.
# =============================================================================

import time, struct, serial, colorsys
from config import SERIAL_PORT, BAUD_RATE, LED_TOTAL

MAGIC = b'\x41\x64\x61\x6C'

def crc8(data):
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc

def invia(p, r, g, b):
    payload = struct.pack('>H', LED_TOTAL) + bytes([r, g, b] * LED_TOTAL)
    p.write(MAGIC + payload + bytes([crc8(payload)]))

def lerp(a, b, t):
    return int(a + (b - a) * t)

print(f"Connessione a {SERIAL_PORT}...")
p = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1, dsrdtr=False, rtscts=False)
p.dtr = False
p.rts = False
time.sleep(2)
print("Avvio ciclo colori — Ctrl+C per fermare\n")

# Velocità: secondi per completare un giro completo della ruota dei colori
DURATA_CICLO = 10.0
# Passi di transizione per ogni cambio colore
PASSI = 60

hue = 0.0
try:
    while True:
        # Colore corrente e successivo sulla ruota HSV
        r1, g1, b1 = [int(x * 255) for x in colorsys.hsv_to_rgb(hue, 1.0, 1.0)]
        hue_next = (hue + 1.0 / PASSI) % 1.0
        r2, g2, b2 = [int(x * 255) for x in colorsys.hsv_to_rgb(hue_next, 1.0, 1.0)]

        # Transizione morbida da colore corrente al successivo
        for step in range(PASSI):
            t = step / PASSI
            r = lerp(r1, r2, t)
            g = lerp(g1, g2, t)
            b = lerp(b1, b2, t)
            invia(p, r, g, b)
            time.sleep(DURATA_CICLO / (PASSI * PASSI))

        hue = hue_next
        print(f"  Hue: {hue:.2f}  RGB({r1},{g1},{b1})", end='\r')

except KeyboardInterrupt:
    print("\nFermato.")
finally:
    p.close()