# =============================================================================
# test_singolo_colore.py
# Manda un unico colore fisso a tutta la striscia, in loop continuo.
# Premi Ctrl+C per fermare (i LED rimarranno accesi finché ESP32 non va in timeout).
#
# Modifica R, G, B qui sotto per testare colori diversi.
# =============================================================================

import time
import struct
import serial
from config import SERIAL_PORT, BAUD_RATE, LED_TOTAL

MAGIC = b'\x41\x64\x61\x6C'  # "Adal" — deve corrispondere al firmware

# ---------- Colore da testare ----------
R = 255
G = 0
B = 0
# ---------------------------------------

def crc8(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc

def pacchetto(r, g, b):
    payload = struct.pack('>H', LED_TOTAL) + bytes([r, g, b] * LED_TOTAL)
    return MAGIC + payload + bytes([crc8(payload)])

def main():
    print(f"Connessione a {SERIAL_PORT} @ {BAUD_RATE}...")
    try:
        p = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1, write_timeout=0.1)
    except serial.SerialException as e:
        print(f"ERRORE: {e}")
        return

    time.sleep(2)  # Attende reset ESP32
    pkt = pacchetto(R, G, B)
    print(f"Invio colore RGB({R},{G},{B}) fisso — Ctrl+C per fermare")
    print(f"Pacchetto: {len(pkt)} byte, CRC={pkt[-1]:#04x}")

    try:
        count = 0
        while True:
            p.write(pkt)
            count += 1
            if count % 30 == 0:
                print(f"  {count} pacchetti inviati...")
            time.sleep(1 / 30)  # 30 fps
    except KeyboardInterrupt:
        print("\nFermato.")
    finally:
        p.close()

if __name__ == "__main__":
    main()