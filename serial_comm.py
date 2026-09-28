# =============================================================================
# serial_comm.py - Comunicazione seriale con ESP32
# Protocollo: MAGIC (4B) + NUM_LED (2B) + RGB×N + CRC8 (1B)
# =============================================================================

import serial
import struct
import time
from config import SERIAL_PORT, BAUD_RATE, LED_TOTAL

LED_COUNT_QUERY = b'\x3f'  # deve corrispondere a LED_COUNT_QUERY nel firmware .ino

MAGIC = b'\x41\x64\x61\x6C'  # "Adal"

def crc8(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc

class SerialManager:

    def __init__(self):
        self.connesso = False
        self.porta = None
        self._connetti()

    def _connetti(self):
        try:
            self.porta = serial.Serial(
                SERIAL_PORT, BAUD_RATE,
                timeout=0,
                write_timeout=0.05,
                dsrdtr=False,   # Disabilita DTR: evita il reset dell'ESP32
                rtscts=False    # Disabilita RTS: evita il reset dell'ESP32
            )
            self.porta.dtr = False
            self.porta.rts = False
            self.connesso = True
            print(f"[Seriale] Connesso a {SERIAL_PORT} @ {BAUD_RATE} baud")
        except serial.SerialException as e:
            self.connesso = False
            print(f"[Seriale] Impossibile connettersi a {SERIAL_PORT}: {e}")
            print(f"[Seriale] Modalità solo preview attiva.")

    def _costruisci_pacchetto(self, colori: list) -> bytes:
        payload = struct.pack('>H', LED_TOTAL)
        for r, g, b in colori:
            payload += bytes([r, g, b])
        return MAGIC + payload + bytes([crc8(payload)])

    def invia_colori(self, colori: list) -> bool:
        if not self.connesso or self.porta is None:
            return False
        try:
            if self.porta.out_waiting > 64:
                self.porta.reset_output_buffer()
            self.porta.write(self._costruisci_pacchetto(colori))
            return True
        except serial.SerialException as e:
            print(f"[Seriale] Errore in scrittura: {e}")
            self.connesso = False
            return False

    def buffer_libero(self) -> bool:
        """True se il buffer TX è vuoto — evita accumulo di pacchetti in ritardo."""
        if not self.connesso or self.porta is None:
            return False
        try:
            return self.porta.out_waiting == 0
        except Exception:
            return False

    def interroga_num_led(self, timeout: float = 1.0) -> int | None:
        """Chiede al firmware quanti LED ha configurati (LED_COUNT nel .ino),
        per verificare che config.LED_TOTAL sia allineato al firmware
        realmente caricato. None se non risponde in tempo (firmware più
        vecchio senza questo comando, o porta non connessa)."""
        if not self.connesso or self.porta is None:
            return None
        try:
            self.porta.reset_input_buffer()
            self.porta.write(LED_COUNT_QUERY)
            deadline = time.time() + timeout
            buf = b''
            while time.time() < deadline and len(buf) < 5:
                chunk = self.porta.read(5 - len(buf))
                if chunk:
                    buf += chunk
                else:
                    time.sleep(0.01)
            if len(buf) == 5 and buf[:3] == b'LED':
                return (buf[3] << 8) | buf[4]
            return None
        except serial.SerialException:
            return None

    def chiudi(self):
        if self.porta and self.porta.is_open:
            self.porta.close()
            print("[Seriale] Porta chiusa.")

    @property
    def stato(self) -> str:
        return f"Connesso ({SERIAL_PORT})" if self.connesso else "Disconnesso (solo preview)"