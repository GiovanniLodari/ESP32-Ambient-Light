import time
import struct
import serial
from config import SERIAL_PORT, BAUD_RATE, LED_TOTAL

MAGIC = b'\x41\x64\x61\x6C'

def crc8(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc

def invia_colore(porta, r, g, b):
    payload = struct.pack('>H', LED_TOTAL) + bytes([r, g, b] * LED_TOTAL)
    pacchetto = MAGIC + payload + bytes([crc8(payload)])
    porta.write(pacchetto)

def main():
    print(f"Test di stabilità avanzato su {SERIAL_PORT}...")
    try:
        # Apriamo con un timeout di lettura per catturare i log dell'ESP32
        p = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
        time.sleep(2)
        p.reset_input_buffer()
        p.reset_output_buffer()
        
        print("Invio sequenza di stress test (300 frame)...")
        for i in range(300):
            color = (255, 255, 255) if i % 2 == 0 else (0, 0, 0)
            invia_colore(p, *color)
            time.sleep(1/30)
            
            # Controlla se l'ESP32 ha inviato messaggi di errore (es: CRC errato)
            if p.in_waiting:
                msg = p.read(p.in_waiting).decode('utf-8', errors='ignore')
                if "CRC" in msg or "mismatch" in msg:
                    print(f"\n[!] Messaggio dall'ESP32: {msg.strip()}")
            
            if i % 50 == 0:
                print(f"  Frame {i}/300...")

        # Assicuriamoci che l'ultimo comando (nero) venga elaborato
        print("\nInvio comando finale di spegnimento e attesa...")
        invia_colore(p, 0, 0, 0)
        time.sleep(0.5) 
        
        # Leggi gli ultimi log
        if p.in_waiting:
            msg = p.read(p.in_waiting).decode('utf-8', errors='ignore')
            print(f"Log finali ESP32: {msg.strip()}")

        p.close()
        print("\nTest completato.")
    except Exception as e:
        print(f"Errore: {e}")

if __name__ == "__main__":
    main()
