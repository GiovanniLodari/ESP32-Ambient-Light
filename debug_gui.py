# =============================================================================
# gui_diagnostica.py - GUI interattiva per calibrazione striscia LED
# Permette di:
#   - Accendere singoli lati per verificare la disposizione fisica
#   - Regolare la profondità di campionamento in tempo reale
#   - Vedere l'anteprima della zona di schermo campionata
# =============================================================================

import sys, time, struct, threading
import numpy as np
import mss
import serial
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QSlider, QLabel, QGroupBox, QGridLayout, QCheckBox
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen, QBrush, QPixmap, QImage
from config import SERIAL_PORT, BAUD_RATE, LED_TOTAL, LED_TOP, LED_RIGHT, LED_BOTTOM, LED_LEFT

MAGIC = b'\x41\x64\x61\x6C'

def crc8(data):
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc

def invia(porta, colori):
    if porta is None: return
    try:
        payload = struct.pack('>H', LED_TOTAL) + bytes([c for rgb in colori for c in rgb])
        porta.write(MAGIC + payload + bytes([crc8(payload)]))
        porta.flush()
    except: pass

# =============================================================================
# Widget anteprima schermo con zona di campionamento evidenziata
# =============================================================================
class AntepimaSchermo(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(480, 270)  # 16:9
        self.depth_ratio = 0.10
        self.lati_attivi = {'top': True, 'right': True, 'bottom': True, 'left': True}
        self.pixmap_schermo = None
        self._aggiorna_screenshot()

    def _aggiorna_screenshot(self):
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            screenshot = sct.grab(monitor)
            img = np.array(screenshot)[:, :, :3][:, :, ::-1]
        h, w = img.shape[:2]
        qimg = QImage(img.tobytes(), w, h, w * 3, QImage.Format.Format_RGB888)
        self.pixmap_schermo = QPixmap.fromImage(qimg).scaled(
            480, 270, Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self.update()

    def set_depth(self, ratio):
        self.depth_ratio = ratio
        self.update()

    def set_lati(self, lati):
        self.lati_attivi = lati
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        w, h = self.width(), self.height()
        dx = int(w * self.depth_ratio)
        dy = int(h * self.depth_ratio)

        # Sfondo screenshot
        if self.pixmap_schermo:
            painter.drawPixmap(0, 0, self.pixmap_schermo)
        else:
            painter.fillRect(0, 0, w, h, QColor(30, 30, 30))

        colori_lato = {
            'top':    QColor(200, 50,  50,  120),
            'right':  QColor(50,  200, 50,  120),
            'bottom': QColor(50,  50,  200, 120),
            'left':   QColor(200, 200, 50,  120),
        }

        # Evidenzia le zone di campionamento
        for lato, colore in colori_lato.items():
            if not self.lati_attivi.get(lato, True): continue
            painter.setBrush(QBrush(colore))
            painter.setPen(Qt.PenStyle.NoPen)
            if lato == 'top':    painter.drawRect(0, 0, w, dy)
            if lato == 'bottom': painter.drawRect(0, h - dy, w, dy)
            if lato == 'left':   painter.drawRect(0, 0, dx, h)
            if lato == 'right':  painter.drawRect(w - dx, 0, dx, h)

        # Bordo
        painter.setPen(QPen(QColor(255, 255, 255, 80), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(0, 0, w - 1, h - 1)


# =============================================================================
# Finestra principale
# =============================================================================
class FinestraDiagnostica(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ambient Light — Calibrazione")
        self.setStyleSheet("background-color: #1e1e1e; color: #ddd;")

        # Connessione seriale
        self.porta = None
        try:
            self.porta = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0,
                                       dsrdtr=False, rtscts=False)
            self.porta.dtr = False
            self.porta.rts = False
        except Exception as e:
            print(f"[Seriale] {e} — modalità preview")

        # Stato
        self.lati_accesi = {'top': False, 'right': False, 'bottom': False, 'left': False}
        self.depth_ratio = 0.10
        self.colori_lato = {
            'top':    (180, 0,   0  ),
            'right':  (0,   180, 0  ),
            'bottom': (0,   0,   180),
            'left':   (180, 180, 0  ),
        }

        self._build_ui()

        # Timer aggiornamento screenshot anteprima
        self.timer_preview = QTimer()
        self.timer_preview.timeout.connect(self.anteprima.update)
        self.timer_preview.start(2000)

        # Invia stato iniziale
        self._invia_stato()

    def _build_ui(self):
        centrale = QWidget()
        self.setCentralWidget(centrale)
        layout = QVBoxLayout(centrale)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # --- Anteprima schermo ---
        self.anteprima = AntepimaSchermo()
        layout.addWidget(self.anteprima, alignment=Qt.AlignmentFlag.AlignHCenter)

        # --- Pulsanti lati ---
        grp_lati = QGroupBox("Lati da accendere")
        grp_lati.setStyleSheet("QGroupBox { color: #aaa; border: 1px solid #444; border-radius: 6px; margin-top: 8px; padding-top: 8px; }")
        grid = QGridLayout(grp_lati)

        stile_btn = """
            QPushButton { background: #2a2a2a; border: 2px solid {color}; border-radius: 6px;
                          color: #ddd; padding: 8px 16px; font-size: 13px; }
            QPushButton:checked { background: {color}; color: #111; font-weight: bold; }
        """

        self.btn_top    = QPushButton("⬆ TOP")
        self.btn_right  = QPushButton("➡ RIGHT")
        self.btn_bottom = QPushButton("⬇ BOTTOM")
        self.btn_left   = QPushButton("⬅ LEFT")
        self.btn_tutti  = QPushButton("✦ TUTTI")
        self.btn_spento = QPushButton("✕ SPENTO")

        for btn, col in [(self.btn_top, '#c83232'), (self.btn_right, '#32c832'),
                         (self.btn_bottom, '#3232c8'), (self.btn_left, '#c8c832')]:
            btn.setCheckable(True)
            btn.setStyleSheet(stile_btn.replace('{color}', col).replace('{color}', col))

        self.btn_tutti.setStyleSheet("QPushButton { background: #2a2a2a; border: 2px solid #888; border-radius: 6px; color: #ddd; padding: 8px 16px; font-size: 13px; } QPushButton:hover { background: #444; }")
        self.btn_spento.setStyleSheet("QPushButton { background: #2a2a2a; border: 2px solid #555; border-radius: 6px; color: #888; padding: 8px 16px; font-size: 13px; } QPushButton:hover { background: #333; }")

        grid.addWidget(self.btn_top,    0, 1)
        grid.addWidget(self.btn_left,   1, 0)
        grid.addWidget(self.btn_tutti,  1, 1)
        grid.addWidget(self.btn_right,  1, 2)
        grid.addWidget(self.btn_bottom, 2, 1)
        grid.addWidget(self.btn_spento, 2, 2)

        self.btn_top.toggled.connect(lambda v: self._toggle_lato('top', v))
        self.btn_right.toggled.connect(lambda v: self._toggle_lato('right', v))
        self.btn_bottom.toggled.connect(lambda v: self._toggle_lato('bottom', v))
        self.btn_left.toggled.connect(lambda v: self._toggle_lato('left', v))
        self.btn_tutti.clicked.connect(self._tutti)
        self.btn_spento.clicked.connect(self._spento)

        layout.addWidget(grp_lati)

        # --- Slider profondità campionamento ---
        grp_depth = QGroupBox("Profondità campionamento (focus verso l'interno)")
        grp_depth.setStyleSheet("QGroupBox { color: #aaa; border: 1px solid #444; border-radius: 6px; margin-top: 8px; padding-top: 8px; }")
        vbox = QVBoxLayout(grp_depth)

        hbox_depth = QHBoxLayout()
        self.lbl_depth = QLabel(f"{int(self.depth_ratio * 100)}%")
        self.lbl_depth.setFixedWidth(40)
        self.lbl_depth.setStyleSheet("color: #fff; font-size: 14px; font-weight: bold;")

        self.slider_depth = QSlider(Qt.Orientation.Horizontal)
        self.slider_depth.setMinimum(2)
        self.slider_depth.setMaximum(30)
        self.slider_depth.setValue(int(self.depth_ratio * 100))
        self.slider_depth.setStyleSheet("QSlider::handle:horizontal { background: #888; width: 16px; border-radius: 8px; }")
        self.slider_depth.valueChanged.connect(self._on_depth_changed)

        hbox_depth.addWidget(QLabel("Bordo"))
        hbox_depth.addWidget(self.slider_depth)
        hbox_depth.addWidget(QLabel("Centro"))
        hbox_depth.addWidget(self.lbl_depth)
        vbox.addLayout(hbox_depth)

        lbl_hint = QLabel("Aumenta se i LED sono spenti a schermo intero — la zona colorata nell'anteprima mostra cosa viene campionato")
        lbl_hint.setStyleSheet("color: #666; font-size: 11px;")
        lbl_hint.setWordWrap(True)
        vbox.addWidget(lbl_hint)

        layout.addWidget(grp_depth)

        # --- Stato seriale ---
        stato_txt = f"Seriale: {'Connesso a ' + SERIAL_PORT if self.porta else 'Disconnesso (solo preview)'}"
        self.lbl_stato = QLabel(stato_txt)
        self.lbl_stato.setStyleSheet("color: #555; font-size: 11px;")
        layout.addWidget(self.lbl_stato)

        self.adjustSize()

    def _toggle_lato(self, lato, acceso):
        self.lati_accesi[lato] = acceso
        self.anteprima.set_lati(self.lati_accesi)
        self._invia_stato()

    def _tutti(self):
        for lato in self.lati_accesi: self.lati_accesi[lato] = True
        self.btn_top.setChecked(True)
        self.btn_right.setChecked(True)
        self.btn_bottom.setChecked(True)
        self.btn_left.setChecked(True)
        self.anteprima.set_lati(self.lati_accesi)
        self._invia_stato()

    def _spento(self):
        for lato in self.lati_accesi: self.lati_accesi[lato] = False
        self.btn_top.setChecked(False)
        self.btn_right.setChecked(False)
        self.btn_bottom.setChecked(False)
        self.btn_left.setChecked(False)
        self.anteprima.set_lati(self.lati_accesi)
        self._invia_stato()

    def _on_depth_changed(self, val):
        self.depth_ratio = val / 100.0
        self.lbl_depth.setText(f"{val}%")
        self.anteprima.set_depth(self.depth_ratio)
        self.anteprima._aggiorna_screenshot()

    def _invia_stato(self):
        """Costruisce la lista colori in base ai lati accesi e invia."""
        colori = []
        for lato, count in [('top', LED_TOP), ('right', LED_RIGHT),
                             ('bottom', LED_BOTTOM), ('left', LED_LEFT)]:
            c = self.colori_lato[lato] if self.lati_accesi[lato] else (0, 0, 0)
            colori += [c] * count
        invia(self.porta, colori)

    def closeEvent(self, event):
        invia(self.porta, [(0, 0, 0)] * LED_TOTAL)
        if self.porta: self.porta.close()
        event.accept()


def main():
    app = QApplication(sys.argv)
    win = FinestraDiagnostica()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()