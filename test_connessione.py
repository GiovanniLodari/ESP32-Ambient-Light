# =============================================================================
# test_connessione.py — script di diagnostica standalone
# Esegui QUESTO prima di main.py per verificare che ESP32 e protocollo funzionino.
#
# Cosa fa:
#   1. Invia ROSSO fisso per 2 secondi
#   2. Invia VERDE fisso per 2 secondi
#   3. Invia BLU fisso per 2 secondi
#   4. Spegne tutto
#
# Se i LED mostrano i colori giusti nell'ordine giusto, hardware e protocollo
# funzionano correttamente e il problema era nel codice Python principale.
# Se i colori sono sbagliati (es. rosso appare verde), modifica COLOR_ORDER nel .ino
# =============================================================================

import time
import struct
import serial
from config import SERIAL_PORT, BAUD_RATE, LED_TOTAL

MAGIC  = b'\x41\x64\x61\x6C'   # "Adal" — deve corrispondere al .ino

def crc8(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc

def invia_colore_solido(porta, r, g, b):
    payload = struct.pack('>H', LED_TOTAL) + bytes([r, g, b] * LED_TOTAL)
    pacchetto = MAGIC + payload + bytes([crc8(payload)])
    porta.write(pacchetto)

def main():
    print(f"Connessione a {SERIAL_PORT} @ {BAUD_RATE}...")
    try:
        p = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
    except serial.SerialException as e:
        print(f"ERRORE: {e}")
        return

    time.sleep(2)  # Attende il reset dell'ESP32 dopo connessione seriale
    print("Connesso. Inizio test colori...\n")

    colori = [
        ("ROSSO",  255,   0,   0),
        ("VERDE",    0, 255,   0),
        ("BLU",      0,   0, 255),
        ("BIANCO", 255, 255, 255),
        ("SPENTO",   0,   0,   0),
    ]

    for nome, r, g, b in colori:
        print(f"  → {nome} ({r},{g},{b})")
        for _ in range(60):          # 2 secondi a 30 fps
            invia_colore_solido(p, r, g, b)
            time.sleep(1/30)

    p.close()
    print("\nTest completato.")
    print("Se i colori erano nell'ordine sbagliato (es. ROSSO appariva VERDE),")
    print("cambia COLOR_ORDER nel .ino: prova RGB, BGR, GRB, RBG, BRG, GBR.")

if __name__ == "__main__":
    main()
