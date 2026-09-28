# =============================================================================
# test_lati.py
# Accende a turno ogni lato della striscia con un colore diverso,
# poi li accende tutti insieme. Utile per verificare che l'ordine
# dei LED corrisponda alla disposizione fisica sul monitor.
#
# Colori per lato:
#   TOP    → ROSSO
#   RIGHT  → VERDE
#   BOTTOM → BLU
#   LEFT   → GIALLO
# =============================================================================

import time, struct, serial
from config import SERIAL_PORT, BAUD_RATE, LED_TOTAL, LED_TOP, LED_RIGHT, LED_BOTTOM, LED_LEFT

MAGIC = b'\x41\x64\x61\x6C'
PAUSA = 3  # secondi per ogni lato

def crc8(data):
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc

def invia(p, colori):
    payload = struct.pack('>H', LED_TOTAL) + bytes([c for rgb in colori for c in rgb])
    p.write(MAGIC + payload + bytes([crc8(payload)]))
    p.flush()

def colori_lato(lato: str, acceso: bool):
    """Costruisce la lista di 60 colori con solo un lato acceso."""
    palette = {
        'top':    (180, 0,   0  ),  # rosso
        'right':  (0,   180, 0  ),  # verde
        'bottom': (0,   0,   180),  # blu
        'left':   (180, 180, 0  ),  # giallo
    }
    spento = (0, 0, 0)
    risultato = []
    # Ordine striscia: TOP → RIGHT → BOTTOM → LEFT
    for nome, count in [('top', LED_TOP), ('right', LED_RIGHT),
                        ('bottom', LED_BOTTOM), ('left', LED_LEFT)]:
        colore = palette[nome] if (acceso and nome == lato) else spento
        risultato += [colore] * count
    return risultato

def tutti_i_lati():
    palette = {
        'top':    (180, 0,   0  ),
        'right':  (0,   180, 0  ),
        'bottom': (0,   0,   180),
        'left':   (180, 180, 0  ),
    }
    risultato = []
    for nome, count in [('top', LED_TOP), ('right', LED_RIGHT),
                        ('bottom', LED_BOTTOM), ('left', LED_LEFT)]:
        risultato += [palette[nome]] * count
    return risultato

print(f"Connessione a {SERIAL_PORT}...")
p = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1, dsrdtr=False, rtscts=False)
p.dtr = False
p.rts = False
time.sleep(2)

lati = ['top', 'right', 'bottom', 'left']
nomi = {'top': 'TOP (rosso)', 'right': 'RIGHT (verde)',
        'bottom': 'BOTTOM (blu)', 'left': 'LEFT (giallo)'}

for lato in lati:
    print(f"→ {nomi[lato]} — {LED_TOP if lato=='top' else LED_RIGHT if lato=='right' else LED_BOTTOM if lato=='bottom' else LED_LEFT} LED")
    invia(p, colori_lato(lato, True))
    time.sleep(PAUSA)

print("→ TUTTI I LATI insieme")
invia(p, tutti_i_lati())
time.sleep(PAUSA)

print("→ SPENTO")
invia(p, [(0,0,0)] * LED_TOTAL)
time.sleep(1)

p.close()
print("\nFine test.")
print("Se un lato si accende nel posto sbagliato, modifica l'ordine")
print("in config.py oppure ruota fisicamente la striscia.")