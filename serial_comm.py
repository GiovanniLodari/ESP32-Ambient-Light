# =============================================================================
# serial_comm.py - Comunicazione seriale con ESP32
# Protocollo: MAGIC (4B) + NUM_LED (2B) + RGB×N + CRC8 (1B)
# =============================================================================

import serial
import struct
import threading
import time
import numpy as np
from config import SERIAL_PORT, BAUD_RATE, LED_TOTAL

LED_COUNT_QUERY = b'\x3f'  # deve corrispondere a LED_COUNT_QUERY nel firmware .ino

MAGIC = b'\x41\x64\x61\x6C'  # "Adal"

def _build_crc8_table() -> list:
    tabella = []
    for n in range(256):
        crc = n
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
        tabella.append(crc)
    return tabella


_CRC8_TABLE = _build_crc8_table()


def crc8(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc = _CRC8_TABLE[crc ^ byte]
    return crc


_HEADER_LED = struct.pack('>H', LED_TOTAL)

class SerialManager:

    def __init__(self):
        self.connesso = False
        self.porta = None
        # Serializza gli accessi alla porta: la scrittura dei colori arriva dal
        # thread di cattura (o dal tick GUI in modalità test), la query LED e
        # la riconnessione dal thread GUI.
        self._lock = threading.Lock()
        self._connetti()

    def _connetti(self, silenzioso: bool = False):
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
            self.porta = None
            if not silenzioso:
                print(f"[Seriale] Impossibile connettersi a {SERIAL_PORT}: {e}")
                print(f"[Seriale] Modalità solo preview attiva.")

    def _segna_disconnesso(self):
        """Chiamare con la porta in errore: chiude l'handle così che
        riconnetti() possa riaprirla."""
        self.connesso = False
        try:
            if self.porta is not None:
                self.porta.close()
        except Exception:
            pass
        self.porta = None

    def riconnetti(self) -> bool:
        """Ritenta l'apertura se la porta è caduta (cavo scollegato, ESP32
        riavviato). Silenzioso finché fallisce, per non riempire la console
        a ogni tentativo. Ritorna True se la porta è (di nuovo) aperta."""
        if self.connesso:
            return True
        with self._lock:
            if not self.connesso:
                self._connetti(silenzioso=True)
            return self.connesso

    def _costruisci_pacchetto(self, colori) -> bytes:
        rgb = np.asarray(colori, dtype=np.uint8).reshape(-1)
        if rgb.size != LED_TOTAL * 3:
            raise ValueError(f"attesi {LED_TOTAL} LED, ricevuti {rgb.size // 3}")
        payload = _HEADER_LED + rgb.tobytes()
        return MAGIC + payload + bytes([crc8(payload)])

    def invia_colori(self, colori) -> bool:
        """`colori`: ndarray (LED_TOTAL, 3) uint8 oppure lista di (r, g, b).
        Non blocca: se un altro thread sta usando la porta il frame viene
        scartato (il successivo arriva comunque entro pochi ms)."""
        if not self.connesso or self.porta is None:
            return False
        if not self._lock.acquire(blocking=False):
            return False
        try:
            porta = self.porta   # copia locale: buffer_libero() può azzerarla
            if not self.connesso or porta is None:
                return False
            porta.write(self._costruisci_pacchetto(colori))
            return True
        except serial.SerialTimeoutException:
            # Buffer TX pieno: non è una disconnessione. Svuota e riprova al
            # prossimo frame invece di dichiarare la porta morta.
            try:
                porta.reset_output_buffer()
            except Exception:
                pass
            return False
        except serial.SerialException as e:
            print(f"[Seriale] Errore in scrittura: {e}")
            self._segna_disconnesso()
            return False
        finally:
            self._lock.release()

    def buffer_libero(self) -> bool:
        """True se il buffer TX è vuoto — evita accumulo di pacchetti in ritardo."""
        porta = self.porta
        if not self.connesso or porta is None:
            return False
        try:
            return porta.out_waiting == 0
        except Exception:
            # out_waiting fallisce quando il dispositivo sparisce: senza
            # questo la porta resterebbe "connessa" per sempre.
            self._segna_disconnesso()
            return False

    def interroga_num_led(self, timeout: float = 1.0) -> int | None:
        """Chiede al firmware quanti LED ha configurati (LED_COUNT nel .ino),
        per verificare che config.LED_TOTAL sia allineato al firmware
        realmente caricato. None se non risponde in tempo (firmware più
        vecchio senza questo comando, o porta non connessa)."""
        if not self.connesso or self.porta is None:
            return None
        with self._lock:
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