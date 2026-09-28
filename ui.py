# =============================================================================
# ui.py - Interfaccia grafica: sidebar di navigazione + pagine di contenuto
# =============================================================================

import winreg
import mss
import numpy as np
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QLabel, QGridLayout, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QSlider, QPushButton, QCheckBox,
    QComboBox, QLineEdit, QFrame, QListWidget, QListWidgetItem, QDoubleSpinBox,
    QButtonGroup, QColorDialog,
)
from PyQt6.QtCore import Qt, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap, QPainter, QBrush, QPen, QColor
import config

CELLA_PX = 26

# Opzioni del dropdown "Target FPS" — deve includere qualunque valore
# possa comparire in config.TARGET_FPS o in un preset salvato, altrimenti
# il fallback su indice sbagliato sovrascrive silenziosamente il valore reale.
FPS_OPZIONI = [30, 60, 120, 144, 240, 300]
FPS_INDICE  = {fps: i for i, fps in enumerate(FPS_OPZIONI)}


# =============================================================================
# Design system — un'unica fonte di verità per colori/spaziature, applicata
# come stylesheet globale invece di stili inline sparsi per ogni widget.
# Selezionato in base a config.THEME/ACCENT_MODE all'IMPORT del modulo: le
# impostazioni salvate vanno perciò applicate a config PRIMA di importare
# ui.py (vedi presets.impostazioni_app_applica_a_config() in main.py),
# altrimenti qui si leggerebbero i default invece dei valori persistiti.
# Cambio tema/accento richiede un riavvio: non c'è nulla di reattivo oltre
# questo punto, tutta la UI viene costruita una sola volta con questi valori.
# =============================================================================
TEMI = {
    "scuro": {
        "BG_WINDOW": "#0d0f12", "BG_SIDEBAR": "#111317", "BG_CARD": "#16181c",
        "BG_INPUT": "#1b1e23", "BG_INPUT_HOVER": "#21252b",
        "BORDER": "#262a30", "BORDER_SOFT": "#1d2025",
        "TEXT_PRIMARY": "#e7e9ec", "TEXT_SECONDARY": "#9aa1ab", "TEXT_MUTED": "#5c636c",
        "SUCCESS": "#59c274", "WARNING": "#e0a458", "DANGER": "#e2596b",
    },
    "chiaro": {
        "BG_WINDOW": "#f4f5f7", "BG_SIDEBAR": "#eef0f3", "BG_CARD": "#ffffff",
        "BG_INPUT": "#f0f1f4", "BG_INPUT_HOVER": "#e4e6ea",
        "BORDER": "#d7dae0", "BORDER_SOFT": "#e3e5e9",
        "TEXT_PRIMARY": "#1a1d21", "TEXT_SECONDARY": "#5b6169", "TEXT_MUTED": "#9096a0",
        "SUCCESS": "#2f9e52", "WARNING": "#c17d1f", "DANGER": "#d13a4f",
    },
}

_TEMA_ATTIVO = TEMI.get(getattr(config, "THEME", "scuro"), TEMI["scuro"])

BG_WINDOW      = _TEMA_ATTIVO["BG_WINDOW"]
BG_SIDEBAR     = _TEMA_ATTIVO["BG_SIDEBAR"]
BG_CARD        = _TEMA_ATTIVO["BG_CARD"]
BG_INPUT       = _TEMA_ATTIVO["BG_INPUT"]
BG_INPUT_HOVER = _TEMA_ATTIVO["BG_INPUT_HOVER"]
BORDER         = _TEMA_ATTIVO["BORDER"]
BORDER_SOFT    = _TEMA_ATTIVO["BORDER_SOFT"]

TEXT_PRIMARY   = _TEMA_ATTIVO["TEXT_PRIMARY"]
TEXT_SECONDARY = _TEMA_ATTIVO["TEXT_SECONDARY"]
TEXT_MUTED     = _TEMA_ATTIVO["TEXT_MUTED"]


def _leggi_colore_accento_windows() -> tuple[int, int, int] | None:
    """Legge il colore accento di sistema (Impostazioni > Personalizzazione >
    Colori) dal registro, così hover/bottoni/checkbox seguono lo stesso
    colore scelto in Windows invece di un blu fisso. None se non leggibile."""
    try:
        chiave = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM")
        valore, _ = winreg.QueryValueEx(chiave, "AccentColor")   # formato 0xAABBGGRR
        blue  = (valore >> 16) & 0xFF
        green = (valore >> 8) & 0xFF
        red   = valore & 0xFF
        return red, green, blue
    except Exception:
        return None


def _tinta_piu_chiara(rgb: tuple[int, int, int], quantita: float = 0.25) -> str:
    r, g, b = rgb
    r = int(r + (255 - r) * quantita)
    g = int(g + (255 - g) * quantita)
    b = int(b + (255 - b) * quantita)
    return f"#{r:02x}{g:02x}{b:02x}"


def _testo_leggibile_su(rgb: tuple[int, int, int]) -> str:
    """Testo scuro su accenti chiari, testo chiaro su accenti scuri — il
    colore di sistema può essere qualunque tinta, non solo un blu chiaro."""
    r, g, b = rgb
    luma = 0.299 * r + 0.587 * g + 0.114 * b
    return "#10141a" if luma > 140 else "#f5f6f8"


def _hex_a_rgb(hex_colore: str) -> tuple[int, int, int]:
    hex_colore = hex_colore.lstrip("#")
    return tuple(int(hex_colore[i:i + 2], 16) for i in (0, 2, 4))


if getattr(config, "ACCENT_MODE", "sistema") == "personalizzato":
    try:
        _ACCENTO_RGB = _hex_a_rgb(getattr(config, "ACCENT_CUSTOM_HEX", "#5b9df6"))
    except Exception:
        _ACCENTO_RGB = (91, 157, 246)
else:
    _ACCENTO_RGB = _leggi_colore_accento_windows() or (91, 157, 246)  # fallback blu

ACCENT        = "#{:02x}{:02x}{:02x}".format(*_ACCENTO_RGB)
ACCENT_HOVER  = _tinta_piu_chiara(_ACCENTO_RGB)
ACCENT_SOFT   = "rgba({}, {}, {}, 40)".format(*_ACCENTO_RGB)
ACCENT_BORDER = "rgba({}, {}, {}, 120)".format(*_ACCENTO_RGB)
ACCENT_TEXT   = _testo_leggibile_su(_ACCENTO_RGB)

SUCCESS = _TEMA_ATTIVO["SUCCESS"]
WARNING = _TEMA_ATTIVO["WARNING"]
DANGER  = _TEMA_ATTIVO["DANGER"]

# Colori semantici dei 4 lati (test LED fisici) — versione desaturata per
# restare coerente con una palette minimale invece di rosso/verde/blu puri.
COLORE_TOP    = "#d97a7a"
COLORE_RIGHT  = "#7ac48a"
COLORE_BOTTOM = "#7a9ad9"
COLORE_LEFT   = "#d9c97a"


def build_qss() -> str:
    return f"""
        QWidget {{
            background: transparent;
            color: {TEXT_PRIMARY};
            font-family: 'Segoe UI', sans-serif;
            font-size: 12px;
        }}
        #Root {{ background: {BG_WINDOW}; }}
        #HeaderBar {{
            background: {BG_WINDOW};
            border-bottom: 1px solid {BORDER_SOFT};
        }}
        #AppTitle {{ color: {TEXT_PRIMARY}; font-size: 14px; font-weight: 600; }}
        #Sidebar {{
            background: {BG_SIDEBAR};
            border-right: 1px solid {BORDER_SOFT};
        }}
        #Card {{
            background: {BG_CARD};
            border: 1px solid {BORDER_SOFT};
            border-radius: 10px;
        }}
        #CardTitle {{
            color: {TEXT_MUTED};
            font-size: 10px;
            font-weight: 700;
        }}
        #FieldLabel {{ color: {TEXT_SECONDARY}; font-size: 11px; }}
        #ValueLabel {{ color: {TEXT_PRIMARY}; font-size: 11px; font-family: Consolas, monospace; }}
        #MutedLabel {{ color: {TEXT_MUTED}; font-size: 10px; }}

        QPushButton#NavButton {{
            background: transparent;
            border: none;
            border-left: 3px solid transparent;
            color: {TEXT_SECONDARY};
            text-align: left;
            padding: 10px 14px 10px 13px;
            font-size: 12px;
        }}
        QPushButton#NavButton:hover {{ background: rgba(255,255,255,12); color: {TEXT_PRIMARY}; }}
        QPushButton#NavButton:checked {{
            background: {ACCENT_SOFT};
            border-left: 3px solid {ACCENT};
            color: {TEXT_PRIMARY};
            font-weight: 600;
        }}

        QPushButton#BtnUtility {{
            background: {BG_INPUT};
            border: 1px solid {BORDER};
            border-radius: 6px;
            color: {TEXT_SECONDARY};
            padding: 6px 14px;
        }}
        QPushButton#BtnUtility:hover {{ background: {BG_INPUT_HOVER}; color: {TEXT_PRIMARY}; }}

        QPushButton#BtnPrimary {{
            background: {ACCENT};
            border: none;
            border-radius: 6px;
            color: {ACCENT_TEXT};
            padding: 6px 16px;
            font-weight: 600;
        }}
        QPushButton#BtnPrimary:hover {{ background: {ACCENT_HOVER}; }}

        QPushButton#BtnLato {{
            background: {BG_INPUT};
            border: 2px solid {BORDER};
            border-radius: 6px;
            color: {TEXT_SECONDARY};
            padding: 9px 10px;
            font-weight: 600;
        }}
        QPushButton#BtnLato:hover {{ background: {BG_INPUT_HOVER}; color: {TEXT_PRIMARY}; }}
        QPushButton#BtnLato:checked {{ color: {BG_WINDOW}; }}

        QLineEdit, QComboBox, QListWidget, QDoubleSpinBox {{
            background: {BG_INPUT};
            border: 1px solid {BORDER};
            border-radius: 6px;
            color: {TEXT_PRIMARY};
            padding: 5px 8px;
        }}
        /* Solo per il testo selezionato dentro i campi editabili — il popup
        del combobox usa invece ACCENT_SOFT (vedi item:selected più sotto),
        altrimenti la riga evidenziata risulta troppo satura rispetto al tema. */
        QLineEdit, QDoubleSpinBox {{ selection-background-color: {ACCENT}; }}

        QLineEdit:hover, QComboBox:hover, QDoubleSpinBox:hover, QListWidget:hover {{
            border-color: {ACCENT_BORDER};
        }}
        QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {ACCENT}; }}

        QComboBox::drop-down {{ border: none; width: 18px; }}
        QComboBox::down-arrow {{
            width: 8px; height: 8px;
            image: none;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-top: 5px solid {TEXT_SECONDARY};
            margin-right: 8px;
        }}
        QComboBox QAbstractItemView {{
            background: {BG_CARD};
            color: {TEXT_PRIMARY};
            selection-background-color: {ACCENT_SOFT};
            border: 1px solid {BORDER};
            outline: none;
            padding: 4px;
        }}
        QComboBox QAbstractItemView::item {{
            padding: 5px 8px;
            border-radius: 4px;
            min-height: 20px;
        }}
        QComboBox QAbstractItemView::item:hover {{
            background: {BG_INPUT_HOVER};
            color: {TEXT_PRIMARY};
        }}
        QComboBox QAbstractItemView::item:selected {{
            background: {ACCENT_SOFT};
            color: {TEXT_PRIMARY};
        }}

        QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
            width: 14px;
            background: {BG_INPUT_HOVER};
            border: none;
        }}
        QDoubleSpinBox::up-button {{ border-top-right-radius: 6px; }}
        QDoubleSpinBox::down-button {{ border-bottom-right-radius: 6px; }}
        QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{ background: {ACCENT_SOFT}; }}
        QDoubleSpinBox::up-arrow {{
            width: 0; height: 0;
            border-left: 3px solid transparent; border-right: 3px solid transparent;
            border-bottom: 4px solid {TEXT_SECONDARY};
        }}
        QDoubleSpinBox::down-arrow {{
            width: 0; height: 0;
            border-left: 3px solid transparent; border-right: 3px solid transparent;
            border-top: 4px solid {TEXT_SECONDARY};
        }}

        QListWidget::item {{ padding: 3px 4px; border-radius: 4px; }}
        QListWidget::item:hover {{ background: {BG_INPUT_HOVER}; }}
        QListWidget::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT_PRIMARY}; }}

        QCheckBox {{ color: {TEXT_SECONDARY}; font-size: 11px; spacing: 8px; }}
        QCheckBox::indicator {{
            width: 14px; height: 14px;
            border: 1px solid {BORDER};
            border-radius: 4px;
            background: {BG_INPUT};
        }}
        QCheckBox::indicator:hover {{ border-color: {ACCENT_BORDER}; }}
        QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
        QCheckBox::indicator:checked:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}

        QSlider::groove:horizontal {{ height: 4px; background: {BG_INPUT}; border-radius: 2px; }}
        QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
        QSlider::handle:horizontal {{
            background: {TEXT_PRIMARY}; width: 14px; height: 14px;
            margin: -5px 0; border-radius: 7px;
        }}
        QSlider::handle:horizontal:hover {{ background: {ACCENT_HOVER}; }}

        QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
        QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 24px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
        QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 5px; min-width: 24px; }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    """


def crea_card(titolo: str = "") -> tuple[QFrame, QVBoxLayout]:
    """Contenitore standard per ogni sezione: sostituisce i vecchi QGroupBox
    con un frame più pulito, coerente con lo stylesheet globale."""
    card = QFrame()
    card.setObjectName("Card")
    v = QVBoxLayout(card)
    v.setContentsMargins(16, 14, 16, 14)
    v.setSpacing(10)
    if titolo:
        lbl = QLabel(titolo.upper())
        lbl.setObjectName("CardTitle")
        v.addWidget(lbl)
    return card, v


def crea_slider_riga(minv, maxv, val, label_fmt, on_change) -> tuple[QWidget, QSlider]:
    """Riga slider + valore. Restituisce anche il riferimento allo slider
    (serve per riapplicarne il valore quando si carica un preset)."""
    row = QWidget()
    hbox = QHBoxLayout(row)
    hbox.setContentsMargins(0, 0, 0, 0)
    lbl = QLabel(label_fmt(val))
    lbl.setObjectName("ValueLabel")
    lbl.setFixedWidth(48)
    sl = QSlider(Qt.Orientation.Horizontal)
    sl.setMinimum(minv)
    sl.setMaximum(maxv)
    sl.setValue(val)
    sl.valueChanged.connect(lambda v: lbl.setText(label_fmt(v)))
    sl.valueChanged.connect(on_change)
    hbox.addWidget(sl)
    hbox.addWidget(lbl)
    return row, sl


def aggiungi_riga(layout: QVBoxLayout, etichetta: str, widget: QWidget):
    row = QHBoxLayout()
    lbl = QLabel(etichetta)
    lbl.setObjectName("FieldLabel")
    lbl.setFixedWidth(148)
    row.addWidget(lbl)
    row.addWidget(widget)
    layout.addLayout(row)


# =============================================================================
# Singolo quadratino LED
# =============================================================================
class CellaLED(QWidget):
    """Disegnata con QPainter invece di setStyleSheet(): con 60 celle
    aggiornate a TARGET_FPS (anche 144+ volte al secondo), setStyleSheet()
    forza un ricalcolo CSS completo ad ogni chiamata — è risultato essere il
    principale consumo di CPU dell'intera app (confermato via profiling).
    paintEvent() è ordini di grandezza più economico, e qui si evita anche
    di ridisegnare quando il colore non è cambiato rispetto al frame prima."""

    def __init__(self, indice: int):
        super().__init__()
        self.indice = indice
        self.setFixedSize(QSize(CELLA_PX, CELLA_PX))
        self._colore = QColor(0, 0, 0)
        self._penna  = QPen(QColor(BORDER_SOFT), 1)

    def imposta_colore(self, r, g, b):
        nuovo = QColor(r, g, b)
        if nuovo != self._colore:
            self._colore = nuovo
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(self._penna)
        painter.setBrush(QBrush(self._colore))
        painter.drawRoundedRect(0, 0, self.width() - 1, self.height() - 1, 5, 5)


# =============================================================================
# Barra statistiche (sotto la griglia LED nella pagina Preview)
# =============================================================================
class StatsBar(QWidget):
    """Mostra fps cattura, fps UI, latenza pipeline, CPU, RAM e VRAM."""

    _STILE_BASE = f"color: {TEXT_SECONDARY}; font-size: 11px; font-family: Consolas, monospace;"
    _STILE_OK   = f"color: {SUCCESS}; font-size: 11px; font-family: Consolas, monospace;"
    _STILE_WARN = f"color: {WARNING}; font-size: 11px; font-family: Consolas, monospace;"
    _STILE_ERR  = f"color: {DANGER}; font-size: 11px; font-family: Consolas, monospace;"

    def __init__(self):
        super().__init__()
        self.setObjectName("Card")
        hbox = QHBoxLayout(self)
        hbox.setContentsMargins(16, 10, 16, 10)
        hbox.setSpacing(0)

        self._lbl = {}
        self._fascia = {}   # ultima fascia colore applicata per chiave (evita setStyleSheet ridondanti)
        items = [
            ("fps_capture", "CAPTURE", "—"),
            ("fps_ui",      "UI",      "—"),
            ("latency_ms",  "LATENZA", "—"),
            ("cpu",         "CPU",     "—"),
            ("ram",         "RAM",     "—"),
            ("vram",        "VRAM",    "—"),
        ]

        for i, (key, etichetta, default) in enumerate(items):
            if i > 0:
                sep = QFrame()
                sep.setFrameShape(QFrame.Shape.VLine)
                sep.setStyleSheet(f"color: {BORDER};")
                hbox.addWidget(sep)
                hbox.addSpacing(10)

            lbl_icon = QLabel(etichetta)
            lbl_icon.setObjectName("MutedLabel")
            lbl_val = QLabel(default)
            lbl_val.setStyleSheet(self._STILE_BASE)
            lbl_val.setMinimumWidth(58)

            hbox.addWidget(lbl_icon)
            hbox.addSpacing(6)
            hbox.addWidget(lbl_val)
            hbox.addSpacing(12)

            self._lbl[key] = lbl_val

    def _applica_fascia(self, chiave: str, fascia: str, stile: str):
        # setStyleSheet() forza un ricalcolo CSS — costoso se ripetuto ad ogni
        # tick (anche 100+ volte/sec) quando la fascia colore non è cambiata.
        if self._fascia.get(chiave) != fascia:
            self._fascia[chiave] = fascia
            self._lbl[chiave].setStyleSheet(stile)

    def aggiorna(self, stats: dict):
        if "fps_capture" in stats:
            v = stats["fps_capture"]
            fascia = "ok" if v >= 60 else "warn" if v >= 30 else "err"
            s = self._STILE_OK if fascia == "ok" else self._STILE_WARN if fascia == "warn" else self._STILE_ERR
            self._lbl["fps_capture"].setText(f"{v:.0f} fps")
            self._applica_fascia("fps_capture", fascia, s)

        if "fps_ui" in stats:
            v = stats["fps_ui"]
            self._lbl["fps_ui"].setText(f"{v:.0f} fps")

        if "latency_ms" in stats:
            v = stats["latency_ms"]
            fascia = "ok" if v < 5 else "warn" if v < 15 else "err"
            s = self._STILE_OK if fascia == "ok" else self._STILE_WARN if fascia == "warn" else self._STILE_ERR
            self._lbl["latency_ms"].setText(f"{v:.1f} ms")
            self._applica_fascia("latency_ms", fascia, s)

        if "cpu" in stats:
            v = stats["cpu"]
            fascia = "ok" if v < 30 else "warn" if v < 60 else "err"
            s = self._STILE_OK if fascia == "ok" else self._STILE_WARN if fascia == "warn" else self._STILE_ERR
            self._lbl["cpu"].setText(f"{v:.1f}%")
            self._applica_fascia("cpu", fascia, s)

        if "ram" in stats:
            self._lbl["ram"].setText(f"{stats['ram']:.0f} MB")

        if "vram" in stats:
            self._lbl["vram"].setText(f"{stats['vram']:.0f} MB")


# =============================================================================
# Anteprima schermo con zone di campionamento evidenziate
# =============================================================================
class AntepimaSchermo(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(440, 248)
        self.depth_ratio  = config.SAMPLE_DEPTH_RATIO
        self.offset_ratio = config.SAMPLE_OFFSET_RATIO
        self.pixmap = None

    def aggiorna_screenshot(self):
        try:
            with mss.mss() as sct:
                monitor = sct.monitors[1]
                shot = sct.grab(monitor)
                img = np.array(shot)[:, :, :3][:, :, ::-1]
            h, w = img.shape[:2]
            qimg = QImage(img.tobytes(), w, h, w * 3, QImage.Format.Format_RGB888)
            self.pixmap = QPixmap.fromImage(qimg).scaled(
                self.width(), self.height(),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            self.update()
        except Exception as e:
            print(f"[Preview] {e}")

    def set_depth(self, ratio):
        self.depth_ratio = ratio
        self.update()

    def set_offset(self, ratio):
        self.offset_ratio = ratio
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        w, h = self.width(), self.height()
        dx = int(w * self.depth_ratio)
        dy = int(h * self.depth_ratio)
        ox = int(w * self.offset_ratio)
        oy = int(h * self.offset_ratio)

        if self.pixmap:
            painter.drawPixmap(0, 0, self.pixmap)
        else:
            painter.fillRect(0, 0, w, h, QColor(BG_INPUT))

        overlay = {
            "top":    (ox,          oy,          w - 2*ox, dy,       QColor(217, 122, 122, 90)),
            "bottom": (ox,          h - oy - dy, w - 2*ox, dy,       QColor(122, 154, 217, 90)),
            "left":   (ox,          oy,          dx,       h - 2*oy, QColor(217, 201, 122, 90)),
            "right":  (w - ox - dx, oy,          dx,       h - 2*oy, QColor(122, 196, 138, 90)),
        }
        painter.setPen(Qt.PenStyle.NoPen)
        for _, (x, y, lw, lh, col) in overlay.items():
            painter.setBrush(QBrush(col))
            painter.drawRect(x, y, lw, lh)

        painter.setPen(QPen(QColor(BORDER), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(0, 0, w - 1, h - 1)


# =============================================================================
# Pagina Preview: griglia LED + barra statistiche
# =============================================================================
class TabPreview(QWidget):
    def __init__(self):
        super().__init__()
        self.celle: list[CellaLED] = []
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        griglia = QGridLayout()
        griglia.setSpacing(3)
        num_righe = config.LED_LEFT + 2
        num_col   = config.LED_TOP  + 2

        # RIGHT: LED 0..LED_RIGHT-1, colonna destra, basso→alto.
        # Righe 1..num_righe-2, le stesse di LEFT — la vecchia formula
        # (num_righe - 1 - i) usava num_righe-1 come riga di partenza invece
        # di num_righe-2, spostando l'intera colonna di una cella verso il
        # basso e facendole "rubare" l'angolo in basso a destra.
        offset_right = 0
        for i in range(config.LED_RIGHT):
            c = CellaLED(offset_right + i)
            griglia.addWidget(c, num_righe - 2 - i, num_col - 1)
            self.celle.append(c)

        # TOP: LED LED_RIGHT..+LED_TOP, riga alta, destra→sinistra
        offset_top = config.LED_RIGHT
        for i in range(config.LED_TOP):
            c = CellaLED(offset_top + i)
            griglia.addWidget(c, 0, num_col - 2 - i)
            self.celle.append(c)

        # LEFT: colonna sinistra, alto→basso
        offset_left = config.LED_RIGHT + config.LED_TOP
        for i in range(config.LED_LEFT):
            c = CellaLED(offset_left + i)
            griglia.addWidget(c, i + 1, 0)
            self.celle.append(c)

        # BOTTOM: riga bassa, sinistra→destra
        offset_bottom = config.LED_RIGHT + config.LED_TOP + config.LED_LEFT
        for i in range(config.LED_BOTTOM):
            c = CellaLED(offset_bottom + i)
            griglia.addWidget(c, num_righe - 1, i + 1)
            self.celle.append(c)

        # Centro
        centro = QLabel("PREVIEW")
        centro.setAlignment(Qt.AlignmentFlag.AlignCenter)
        centro.setStyleSheet(
            f"background-color: {BG_CARD}; color: {TEXT_MUTED}; font-size: 11px;"
            f"font-weight: 700; border: 1px solid {BORDER_SOFT}; border-radius: 8px;"
        )
        griglia.addWidget(centro, 1, 1, num_righe - 2, num_col - 2)

        # La griglia ha già una larghezza fissa (celle a dimensione fissa): uno
        # stretch ai lati evita che il placeholder centrale si espanda a
        # riempire tutta la larghezza della finestra.
        riga_griglia = QHBoxLayout()
        riga_griglia.addStretch()
        riga_griglia.addLayout(griglia)
        riga_griglia.addStretch()
        layout.addLayout(riga_griglia)

        info = QLabel(
            f"Totale {config.LED_TOTAL} LED  ·  "
            f"Top {config.LED_TOP}  Left {config.LED_LEFT}  "
            f"Bottom {config.LED_BOTTOM}  Right {config.LED_RIGHT}"
        )
        info.setObjectName("MutedLabel")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(info)

        layout.addStretch()

        # ---- Barra statistiche ----
        self.stats_bar = StatsBar()
        riga_stats = QHBoxLayout()
        riga_stats.addStretch()
        riga_stats.addWidget(self.stats_bar)
        riga_stats.addStretch()
        layout.addLayout(riga_stats)

    def aggiorna_colori(self, colori: list):
        for i, (r, g, b) in enumerate(colori):
            if i < len(self.celle):
                self.celle[i].imposta_colore(r, g, b)

    def aggiorna_stats(self, stats: dict):
        self.stats_bar.aggiorna(stats)


# =============================================================================
# TabImpostazioni — logica e segnali invariati; il contenuto è distribuito
# su 4 pagine (Calibrazione, Parametri, Profili, Colore) invece che impilato
# in un'unica scheda, per evitare che la finestra cresca a dismisura.
# =============================================================================
class TabImpostazioni(QWidget):
    # Parametri
    depth_cambiato       = pyqtSignal(float)
    offset_cambiato       = pyqtSignal(float)
    gamma_cambiato        = pyqtSignal(float)
    soglia_cambiata       = pyqtSignal(int)
    smoothing_cambiato    = pyqtSignal(float)
    snap_cambiato         = pyqtSignal(int)
    fps_cambiato          = pyqtSignal(int)
    saturazione_cambiata  = pyqtSignal(float)
    blackbar_cambiato     = pyqtSignal(bool)
    color_matrix_cambiata = pyqtSignal(list)   # matrice 3x3 come lista di liste
    # Test lati
    lati_test_cambiati   = pyqtSignal(dict)
    modalita_test        = pyqtSignal(bool)
    # Preset
    preset_salvato       = pyqtSignal(str)   # nome preset
    preset_caricato      = pyqtSignal(str)   # nome preset
    preset_eliminato     = pyqtSignal(str)   # nome preset
    # Profili automatici per app
    app_mapping_aggiunta = pyqtSignal(str, str)   # (exe, nome_preset)
    app_mapping_rimossa  = pyqtSignal(str)        # exe
    # Aspetto
    tray_cambiato          = pyqtSignal(bool)
    bordo_finestra_cambiato = pyqtSignal(str)   # "nativo" | "senza_bordo"
    tema_cambiato          = pyqtSignal(str)    # "scuro" | "chiaro"
    accent_mode_cambiato   = pyqtSignal(str)    # "sistema" | "personalizzato"
    accent_custom_cambiato = pyqtSignal(str)    # colore esadecimale "#rrggbb"

    def __init__(self):
        super().__init__()
        self.in_test      = False
        self.lati_accesi  = {"top": False, "right": False, "bottom": False, "left": False}
        self._build()

        self.timer_shot = QTimer()
        self.timer_shot.timeout.connect(self.anteprima.aggiorna_screenshot)
        self.timer_shot.start(2000)
        self.anteprima.aggiorna_screenshot()

    # -----------------------------------------------------------------------
    # Build: crea le 4 pagine come attributi (pagina_calibrazione, ecc.) —
    # è FinestraAmbientLight a montarle nello QStackedWidget della sidebar.
    # -----------------------------------------------------------------------
    def _build(self):
        self.pagina_calibrazione = self._pagina_calibrazione()
        self.pagina_parametri    = self._pagina_parametri()
        self.pagina_profili      = self._pagina_profili()
        self.pagina_colore       = self._pagina_colore()
        self.pagina_aspetto      = self._pagina_aspetto()

    def _pagina(self) -> tuple[QWidget, QVBoxLayout]:
        pagina = QWidget()
        v = QVBoxLayout(pagina)
        v.setContentsMargins(24, 24, 24, 24)
        v.setSpacing(16)
        return pagina, v

    # ---- Pagina: Calibrazione ---------------------------------------------
    def _pagina_calibrazione(self) -> QWidget:
        pagina, v = self._pagina()

        card_ant, v_ant = crea_card("Anteprima schermo")
        self.anteprima = AntepimaSchermo()
        riga_ant = QHBoxLayout()
        riga_ant.addStretch()
        riga_ant.addWidget(self.anteprima)
        riga_ant.addStretch()
        v_ant.addLayout(riga_ant)

        row_w, self._sl_depth = crea_slider_riga(
            2, 30, int(config.SAMPLE_DEPTH_RATIO * 100),
            lambda v: f"{v}%",
            lambda v: self.depth_cambiato.emit(v / 100.0))
        aggiungi_riga(v_ant, "Profondità bordo", row_w)

        row_w, self._sl_offset = crea_slider_riga(
            0, 40, int(config.SAMPLE_OFFSET_RATIO * 100),
            lambda v: f"{v}%",
            lambda v: self.offset_cambiato.emit(v / 100.0))
        aggiungi_riga(v_ant, "Offset dal bordo", row_w)

        v.addWidget(card_ant)

        card_lati, v_lati = crea_card("Test lati (accende i LED fisici con colori fissi)")

        self.btn_top    = QPushButton("▲  TOP");    self.btn_top.setCheckable(True)
        self.btn_right  = QPushButton("▶  RIGHT");  self.btn_right.setCheckable(True)
        self.btn_bottom = QPushButton("▼  BOTTOM"); self.btn_bottom.setCheckable(True)
        self.btn_left   = QPushButton("◀  LEFT");   self.btn_left.setCheckable(True)
        self.btn_tutti  = QPushButton("Tutti")
        self.btn_off    = QPushButton("Spento")

        for b, colore in [(self.btn_top, COLORE_TOP), (self.btn_right, COLORE_RIGHT),
                          (self.btn_bottom, COLORE_BOTTOM), (self.btn_left, COLORE_LEFT)]:
            b.setObjectName("BtnLato")
            b.setStyleSheet(f"#BtnLato {{ border-color: {colore}; }} "
                            f"#BtnLato:checked {{ background: {colore}; border-color: {colore}; }}")
        self.btn_tutti.setObjectName("BtnUtility")
        self.btn_off.setObjectName("BtnUtility")

        cross = QGridLayout()
        cross.setSpacing(6)
        cross.addWidget(self.btn_top,    0, 1)
        cross.addWidget(self.btn_left,   1, 0)
        cross.addWidget(self.btn_tutti,  1, 1)
        cross.addWidget(self.btn_right,  1, 2)
        cross.addWidget(self.btn_bottom, 2, 1)
        cross.addWidget(self.btn_off,    2, 2)
        v_lati.addLayout(cross)

        self.chk_test = QCheckBox("Blocca Ambient Light durante il test")
        self.chk_test.setChecked(True)
        v_lati.addWidget(self.chk_test)

        self.btn_top.toggled.connect(lambda v: self._toggle("top", v))
        self.btn_right.toggled.connect(lambda v: self._toggle("right", v))
        self.btn_bottom.toggled.connect(lambda v: self._toggle("bottom", v))
        self.btn_left.toggled.connect(lambda v: self._toggle("left", v))
        self.btn_tutti.clicked.connect(self._tutti)
        self.btn_off.clicked.connect(self._spento)

        v.addWidget(card_lati)
        v.addStretch()
        return pagina

    # ---- Pagina: Parametri --------------------------------------------------
    def _pagina_parametri(self) -> QWidget:
        pagina, v = self._pagina()

        card, v_par = crea_card("Colore & risposta")

        row_w, self._sl_gamma = crea_slider_riga(
            10, 30, int(config.GAMMA * 10),
            lambda v: f"{v/10:.1f}",
            lambda v: self.gamma_cambiato.emit(v / 10.0))
        aggiungi_riga(v_par, "Gamma", row_w)

        row_w, self._sl_sat = crea_slider_riga(
            10, 40, int(config.SATURATION_BOOST * 10),
            lambda v: f"{v/10:.1f}x",
            lambda v: self.saturazione_cambiata.emit(v / 10.0))
        aggiungi_riga(v_par, "Saturazione", row_w)

        row_w, self._sl_soglia = crea_slider_riga(
            0, 60, config.SOGLIA_MINIMA,
            lambda v: str(v),
            lambda v: self.soglia_cambiata.emit(v))
        aggiungi_riga(v_par, "Soglia minima", row_w)

        row_w, self._sl_smoothing = crea_slider_riga(
            0, 95, int(config.SMOOTHING_FACTOR * 100),
            lambda v: f"{v}%" if v > 0 else "OFF",
            lambda v: self.smoothing_cambiato.emit(v / 100.0))
        aggiungi_riga(v_par, "Smoothing", row_w)

        snap_default = getattr(config, "SNAP_THRESHOLD", 80)
        row_w, self._sl_snap = crea_slider_riga(
            0, 255, snap_default,
            lambda v: str(v) if v > 0 else "OFF",
            lambda v: self.snap_cambiato.emit(v))
        aggiungi_riga(v_par, "Snap soglia (scena)", row_w)

        v.addWidget(card)

        card2, v_perf = crea_card("Performance")

        self.combo_fps = QComboBox()
        for fps in FPS_OPZIONI:
            self.combo_fps.addItem(f"{fps} Hz", fps)
        idx = FPS_INDICE.get(config.TARGET_FPS, 1)
        self.combo_fps.setCurrentIndex(idx)
        self.combo_fps.currentIndexChanged.connect(
            lambda: self.fps_cambiato.emit(self.combo_fps.currentData()))
        aggiungi_riga(v_perf, "Target FPS", self.combo_fps)

        self.chk_blackbar = QCheckBox("Rileva barre nere (letterbox/pillarbox)")
        self.chk_blackbar.setChecked(getattr(config, "BLACKBAR_DETECTION", True))
        self.chk_blackbar.toggled.connect(self.blackbar_cambiato.emit)
        v_perf.addWidget(self.chk_blackbar)

        v.addWidget(card2)
        v.addStretch()
        return pagina

    # ---- Pagina: Profili -----------------------------------------------------
    def _pagina_profili(self) -> QWidget:
        pagina, v = self._pagina()

        card, v_p = crea_card("Preset — salva e ricarica configurazioni")

        row1 = QHBoxLayout()
        self.edit_nome_preset = QLineEdit()
        self.edit_nome_preset.setPlaceholderText("Nome preset…")
        self.btn_salva_preset = QPushButton("Salva")
        self.btn_salva_preset.setObjectName("BtnPrimary")
        row1.addWidget(self.edit_nome_preset, 1)
        row1.addWidget(self.btn_salva_preset)
        v_p.addLayout(row1)

        row2 = QHBoxLayout()
        self.combo_preset = QComboBox()
        self.btn_carica_preset  = QPushButton("Carica")
        self.btn_elimina_preset = QPushButton("Elimina")
        self.btn_carica_preset.setObjectName("BtnUtility")
        self.btn_elimina_preset.setObjectName("BtnUtility")
        row2.addWidget(self.combo_preset, 1)
        row2.addWidget(self.btn_carica_preset)
        row2.addWidget(self.btn_elimina_preset)
        v_p.addLayout(row2)

        self.combo_preset.currentTextChanged.connect(
            lambda t: self.edit_nome_preset.setText(t) if t else None
        )
        self.btn_salva_preset.clicked.connect(self._on_salva_preset)
        self.btn_carica_preset.clicked.connect(self._on_carica_preset)
        self.btn_elimina_preset.clicked.connect(self._on_elimina_preset)

        v.addWidget(card)

        card2, v_app = crea_card("Switch automatico per app (processo in primo piano)")

        row_app1 = QHBoxLayout()
        self.edit_app_exe = QLineEdit()
        self.edit_app_exe.setPlaceholderText("nome_processo.exe")
        self.combo_app_preset = QComboBox()
        self.btn_app_aggiungi = QPushButton("Aggiungi")
        self.btn_app_aggiungi.setObjectName("BtnPrimary")
        row_app1.addWidget(self.edit_app_exe, 1)
        row_app1.addWidget(self.combo_app_preset)
        row_app1.addWidget(self.btn_app_aggiungi)
        v_app.addLayout(row_app1)

        self.lista_app_mappe = QListWidget()
        self.lista_app_mappe.setFixedHeight(84)
        v_app.addWidget(self.lista_app_mappe)

        self.btn_app_rimuovi = QPushButton("Rimuovi selezionato")
        self.btn_app_rimuovi.setObjectName("BtnUtility")
        v_app.addWidget(self.btn_app_rimuovi)

        self.lbl_auto_stato = QLabel("Auto: —")
        self.lbl_auto_stato.setObjectName("MutedLabel")
        v_app.addWidget(self.lbl_auto_stato)

        self.btn_app_aggiungi.clicked.connect(self._on_app_aggiungi)
        self.btn_app_rimuovi.clicked.connect(self._on_app_rimuovi)

        v.addWidget(card2)
        v.addStretch()
        return pagina

    # ---- Pagina: Colore --------------------------------------------------
    def _pagina_colore(self) -> QWidget:
        pagina, v = self._pagina()

        card, v_col = crea_card("Color correction — bilanciamento bianco della strip")

        grid_color = QGridLayout()
        grid_color.setSpacing(6)
        for j, etichetta in enumerate(["R", "G", "B"]):
            lbl = QLabel(etichetta)
            lbl.setObjectName("MutedLabel")
            lbl.setFixedWidth(68)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid_color.addWidget(lbl, 0, j + 1)

        self._spin_matrix: list[list[QDoubleSpinBox]] = []
        for i, etichetta_riga in enumerate(["R", "G", "B"]):
            lbl_riga = QLabel(f"{etichetta_riga} →")
            lbl_riga.setObjectName("MutedLabel")
            grid_color.addWidget(lbl_riga, i + 1, 0)
            riga_spin = []
            for j in range(3):
                sb = QDoubleSpinBox()
                sb.setRange(-0.5, 2.0)
                sb.setSingleStep(0.05)
                sb.setDecimals(2)
                sb.setFixedWidth(68)
                sb.setValue(config.COLOR_MATRIX[i][j])
                sb.valueChanged.connect(self._on_color_matrix_cambiata)
                grid_color.addWidget(sb, i + 1, j + 1)
                riga_spin.append(sb)
            self._spin_matrix.append(riga_spin)

        riga_grid = QHBoxLayout()
        riga_grid.addStretch()
        riga_grid.addLayout(grid_color)
        riga_grid.addStretch()
        v_col.addLayout(riga_grid)

        self.btn_reset_matrix = QPushButton("Reset a identità")
        self.btn_reset_matrix.setObjectName("BtnUtility")
        self.btn_reset_matrix.clicked.connect(self._on_reset_color_matrix)
        v_col.addWidget(self.btn_reset_matrix, alignment=Qt.AlignmentFlag.AlignHCenter)

        v.addWidget(card)
        v.addStretch()
        return pagina

    # ---- Pagina: Aspetto --------------------------------------------------
    def _pagina_aspetto(self) -> QWidget:
        pagina, v = self._pagina()

        card, v_tray = crea_card("Icona nella barra applicazioni")

        self.chk_tray = QCheckBox("Mostra l'icona nella system tray")
        self.chk_tray.setChecked(getattr(config, "TRAY_ICON_ENABLED", False))
        self.chk_tray.toggled.connect(self.tray_cambiato.emit)
        v_tray.addWidget(self.chk_tray)

        lbl_tray_info = QLabel(
            "Click sinistro sull'icona: mostra/nasconde la finestra. "
            "Click destro: menu Mostra/Esci. Chiudendo dalla X, l'app resta "
            "attiva in tray invece di chiudersi."
        )
        lbl_tray_info.setObjectName("MutedLabel")
        lbl_tray_info.setWordWrap(True)
        v_tray.addWidget(lbl_tray_info)

        v.addWidget(card)

        card_bordo, v_bordo = crea_card("Bordo della finestra")

        riga_bordo = QHBoxLayout()
        lbl_bordo = QLabel("Tipo di bordo")
        lbl_bordo.setObjectName("FieldLabel")
        lbl_bordo.setFixedWidth(148)
        self.combo_bordo = QComboBox()
        self.combo_bordo.addItem("Nativo (Windows)", "nativo")
        self.combo_bordo.addItem("Senza bordo (stile Mac)", "senza_bordo")
        idx_bordo = 1 if getattr(config, "WINDOW_BORDER", "nativo") == "senza_bordo" else 0
        self.combo_bordo.setCurrentIndex(idx_bordo)
        self.combo_bordo.currentIndexChanged.connect(
            lambda: self.bordo_finestra_cambiato.emit(self.combo_bordo.currentData()))
        riga_bordo.addWidget(lbl_bordo)
        riga_bordo.addWidget(self.combo_bordo)
        v_bordo.addLayout(riga_bordo)

        lbl_bordo_info = QLabel("Riavvia l'app per applicare il cambio di bordo.")
        lbl_bordo_info.setObjectName("MutedLabel")
        v_bordo.addWidget(lbl_bordo_info)

        v.addWidget(card_bordo)

        # ---- Tema ----------------------------------------------------------
        card_tema, v_tema = crea_card("Tema")

        riga_tema = QHBoxLayout()
        tema_attuale = getattr(config, "THEME", "scuro")
        self.gruppo_tema = QButtonGroup(self)
        self.gruppo_tema.setExclusive(True)
        for etichetta, valore in (("Scuro", "scuro"), ("Chiaro", "chiaro")):
            b = QPushButton(etichetta)
            b.setCheckable(True)
            b.setObjectName("BtnLato")
            b.setStyleSheet(
                f"QPushButton#BtnLato:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}")
            b.setChecked(valore == tema_attuale)
            b.toggled.connect(
                lambda acceso, v=valore: acceso and self.tema_cambiato.emit(v))
            self.gruppo_tema.addButton(b)
            riga_tema.addWidget(b)
        v_tema.addLayout(riga_tema)

        lbl_tema_info = QLabel("Riavvia l'app per applicare il cambio di tema.")
        lbl_tema_info.setObjectName("MutedLabel")
        v_tema.addWidget(lbl_tema_info)

        v.addWidget(card_tema)

        # ---- Colore accento --------------------------------------------------
        card_accent, v_accent = crea_card("Colore accento")

        riga_modo = QHBoxLayout()
        modo_attuale = getattr(config, "ACCENT_MODE", "sistema")
        self.gruppo_accent_modo = QButtonGroup(self)
        self.gruppo_accent_modo.setExclusive(True)
        btn_sistema = QPushButton("Colore di sistema")
        btn_personalizzato = QPushButton("Tinta unita")
        for b, valore in ((btn_sistema, "sistema"), (btn_personalizzato, "personalizzato")):
            b.setCheckable(True)
            b.setObjectName("BtnLato")
            b.setStyleSheet(
                f"QPushButton#BtnLato:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}")
            b.setChecked(valore == modo_attuale)
            b.toggled.connect(
                lambda acceso, v=valore: acceso and self.accent_mode_cambiato.emit(v))
            self.gruppo_accent_modo.addButton(b)
            riga_modo.addWidget(b)
        v_accent.addLayout(riga_modo)

        contenitore_custom = QWidget()
        v_custom = QVBoxLayout(contenitore_custom)
        v_custom.setContentsMargins(0, 6, 0, 0)
        v_custom.setSpacing(8)

        griglia = QHBoxLayout()
        griglia.setSpacing(8)
        colori_preset = [
            "#5b9df6", "#8b7cf6", "#e05fa0", "#e5484d", "#f2994a",
            "#e0b93a", "#4caf6e", "#3ec6c6", "#9099a8",
        ]
        hex_attuale = getattr(config, "ACCENT_CUSTOM_HEX", "#5b9df6").lower()
        self.gruppo_swatch = QButtonGroup(self)
        self.gruppo_swatch.setExclusive(True)
        for colore in colori_preset:
            sw = QPushButton()
            sw.setCheckable(True)
            sw.setFixedSize(26, 26)
            sw.setChecked(colore.lower() == hex_attuale)
            sw.setStyleSheet(
                f"QPushButton {{ background: {colore}; border: 2px solid {colore}; border-radius: 13px; }} "
                f"QPushButton:checked {{ border: 2px solid {TEXT_PRIMARY}; }}"
            )
            sw.clicked.connect(lambda _=False, c=colore: self._imposta_accent_custom(c))
            self.gruppo_swatch.addButton(sw)
            griglia.addWidget(sw)
        griglia.addStretch()
        v_custom.addLayout(griglia)

        btn_picker = QPushButton("Personalizzato…")
        btn_picker.setObjectName("BtnUtility")
        btn_picker.clicked.connect(self._apri_color_picker)
        v_custom.addWidget(btn_picker, alignment=Qt.AlignmentFlag.AlignLeft)

        contenitore_custom.setVisible(modo_attuale == "personalizzato")
        btn_personalizzato.toggled.connect(contenitore_custom.setVisible)
        v_accent.addWidget(contenitore_custom)

        lbl_accent_info = QLabel("Riavvia l'app per applicare il nuovo colore accento.")
        lbl_accent_info.setObjectName("MutedLabel")
        v_accent.addWidget(lbl_accent_info)

        v.addWidget(card_accent)

        v.addStretch()
        return pagina

    def _imposta_accent_custom(self, colore_hex: str):
        self.accent_custom_cambiato.emit(colore_hex)

    def _apri_color_picker(self):
        iniziale = QColor(getattr(config, "ACCENT_CUSTOM_HEX", "#5b9df6"))
        colore = QColorDialog.getColor(iniziale, self, "Scegli il colore accento")
        if colore.isValid():
            for sw in self.gruppo_swatch.buttons():
                sw.setChecked(False)
            self.accent_custom_cambiato.emit(colore.name())

    # -----------------------------------------------------------------------
    # Slot test lati
    # -----------------------------------------------------------------------
    def _toggle(self, lato, acceso):
        self.lati_accesi[lato] = acceso
        ha_qualcosa = any(self.lati_accesi.values())
        if self.chk_test.isChecked():
            self.modalita_test.emit(ha_qualcosa)
        self.lati_test_cambiati.emit(dict(self.lati_accesi))

    def _tutti(self):
        for l in self.lati_accesi:
            self.lati_accesi[l] = True
        for b in [self.btn_top, self.btn_right, self.btn_bottom, self.btn_left]:
            b.setChecked(True)
        if self.chk_test.isChecked():
            self.modalita_test.emit(True)
        self.lati_test_cambiati.emit(dict(self.lati_accesi))

    def _spento(self):
        for l in self.lati_accesi:
            self.lati_accesi[l] = False
        for b in [self.btn_top, self.btn_right, self.btn_bottom, self.btn_left]:
            b.setChecked(False)
        self.modalita_test.emit(False)
        self.lati_test_cambiati.emit(dict(self.lati_accesi))

    # -----------------------------------------------------------------------
    # Slot preset
    # -----------------------------------------------------------------------
    def _on_salva_preset(self):
        nome = self.edit_nome_preset.text().strip()
        if nome:
            self.preset_salvato.emit(nome)

    def _on_carica_preset(self):
        nome = self.combo_preset.currentText().strip()
        if nome:
            self.preset_caricato.emit(nome)

    def _on_elimina_preset(self):
        nome = self.combo_preset.currentText().strip()
        if nome:
            self.preset_eliminato.emit(nome)

    # -----------------------------------------------------------------------
    # Slot profili per app
    # -----------------------------------------------------------------------
    def _on_app_aggiungi(self):
        exe  = self.edit_app_exe.text().strip()
        nome = self.combo_app_preset.currentText().strip()
        if exe and nome:
            self.app_mapping_aggiunta.emit(exe, nome)
            self.edit_app_exe.clear()

    def _on_app_rimuovi(self):
        item = self.lista_app_mappe.currentItem()
        if item:
            exe = item.data(Qt.ItemDataRole.UserRole)
            self.app_mapping_rimossa.emit(exe)

    # -----------------------------------------------------------------------
    # Slot color correction matrix
    # -----------------------------------------------------------------------
    def _matrice_corrente(self) -> list:
        return [[sb.value() for sb in riga] for riga in self._spin_matrix]

    def _on_color_matrix_cambiata(self, _val=None):
        self.color_matrix_cambiata.emit(self._matrice_corrente())

    def _on_reset_color_matrix(self):
        identita = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        for i in range(3):
            for j in range(3):
                self._spin_matrix[i][j].blockSignals(True)
                self._spin_matrix[i][j].setValue(identita[i][j])
                self._spin_matrix[i][j].blockSignals(False)
        self.color_matrix_cambiata.emit(identita)

    # -----------------------------------------------------------------------
    # API pubblica per il controller (invariata)
    # -----------------------------------------------------------------------
    def aggiorna_lista_preset(self, nomi: list, selezionato: str = ""):
        """Ricarica il dropdown con la lista preset aggiornata."""
        self.combo_preset.blockSignals(True)
        self.combo_preset.clear()
        for n in nomi:
            self.combo_preset.addItem(n)
        if selezionato and selezionato in nomi:
            self.combo_preset.setCurrentText(selezionato)
        self.combo_preset.blockSignals(False)

        self.combo_app_preset.blockSignals(True)
        self.combo_app_preset.clear()
        for n in nomi:
            self.combo_app_preset.addItem(n)
        self.combo_app_preset.blockSignals(False)

    def aggiorna_mappe_app(self, mappa: dict):
        """Ricarica la lista delle mappature processo→preset."""
        self.lista_app_mappe.clear()
        for exe, nome in sorted(mappa.items()):
            item = QListWidgetItem(f"{exe}  →  {nome}")
            item.setData(Qt.ItemDataRole.UserRole, exe)
            self.lista_app_mappe.addItem(item)

    def aggiorna_stato_auto(self, testo: str):
        self.lbl_auto_stato.setText(f"Auto: {testo}")

    def applica_valori(self, params: dict):
        """Aggiorna tutti gli slider con i valori del preset (i segnali si attivano normalmente)."""
        mapping = {
            "SAMPLE_DEPTH_RATIO":  (self._sl_depth,     lambda v: int(v * 100)),
            "SAMPLE_OFFSET_RATIO": (self._sl_offset,    lambda v: int(v * 100)),
            "GAMMA":               (self._sl_gamma,     lambda v: int(v * 10)),
            "SATURATION_BOOST":    (self._sl_sat,       lambda v: int(v * 10)),
            "SOGLIA_MINIMA":       (self._sl_soglia,    lambda v: int(v)),
            "SMOOTHING_FACTOR":    (self._sl_smoothing, lambda v: int(v * 100)),
            "SNAP_THRESHOLD":      (self._sl_snap,      lambda v: int(v)),
        }
        for key, (slider, to_int) in mapping.items():
            if key in params:
                slider.setValue(to_int(params[key]))  # attiva valueChanged → aggiorna config

        if "TARGET_FPS" in params:
            idx = FPS_INDICE.get(params["TARGET_FPS"], 1)
            self.combo_fps.setCurrentIndex(idx)

        if "COLOR_MATRIX" in params:
            m = params["COLOR_MATRIX"]
            for i in range(3):
                for j in range(3):
                    self._spin_matrix[i][j].setValue(m[i][j])  # attiva valueChanged → aggiorna config

    def aggiorna_depth_anteprima(self, ratio):
        self.anteprima.set_depth(ratio)
        self.anteprima.aggiorna_screenshot()

    def aggiorna_offset_anteprima(self, ratio):
        self.anteprima.set_offset(ratio)
        self.anteprima.aggiorna_screenshot()


# =============================================================================
# Sidebar di navigazione
# =============================================================================
class Sidebar(QWidget):
    sezione_cambiata = pyqtSignal(int)

    VOCI = [
        ("▶", "Preview"),
        ("◎", "Calibrazione"),
        ("▬", "Parametri"),
        ("▥", "Profili"),
        ("◐", "Colore"),
        ("◑", "Aspetto"),
    ]

    def __init__(self):
        super().__init__()
        self.setObjectName("Sidebar")
        self.setFixedWidth(190)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 12, 0, 12)
        v.setSpacing(2)

        self.gruppo = QButtonGroup(self)
        self.gruppo.setExclusive(True)
        for i, (icona, etichetta) in enumerate(self.VOCI):
            b = QPushButton(f"{icona}   {etichetta}")
            b.setObjectName("NavButton")
            b.setCheckable(True)
            b.clicked.connect(lambda _, i=i: self.sezione_cambiata.emit(i))
            self.gruppo.addButton(b, i)
            v.addWidget(b)
        self.gruppo.button(0).setChecked(True)

        v.addStretch()
        footer = QLabel("")
        footer.setObjectName("MutedLabel")
        footer.setContentsMargins(14, 0, 0, 0)
        v.addWidget(footer)


# =============================================================================
# Pillola di stato connessione seriale
# =============================================================================
class StatusPill(QWidget):
    def __init__(self):
        super().__init__()
        hbox = QHBoxLayout(self)
        hbox.setContentsMargins(0, 0, 0, 0)
        hbox.setSpacing(6)
        self._dot   = QLabel("●")
        self._testo = QLabel("")
        self._testo.setObjectName("FieldLabel")
        hbox.addWidget(self._dot)
        hbox.addWidget(self._testo)
        self._ultimo_stato: tuple[str, bool] | None = None

    def imposta(self, testo: str, connesso: bool):
        # aggiorna_stato_seriale() viene chiamato ad ogni tick (anche 100+
        # volte al secondo) ma lo stato quasi mai cambia: setStyleSheet() è
        # un'operazione costosa da non ripetere quando non serve.
        if (testo, connesso) == self._ultimo_stato:
            return
        self._ultimo_stato = (testo, connesso)
        colore = SUCCESS if connesso else TEXT_MUTED
        self._dot.setStyleSheet(f"color: {colore}; font-size: 9px;")
        self._testo.setText(testo)


def _e_ingrandita(finestra: QMainWindow) -> bool:
    """True se la finestra è massimizzata O a schermo intero. Su una finestra
    senza bordo, Qt6/Windows porta showMaximized() in stato FullScreen invece
    di Maximized (verificato) — isMaximized() da solo non lo rileverebbe mai,
    rompendo il toggle massimizza/ripristina."""
    stato = finestra.windowState()
    return bool(stato & (Qt.WindowState.WindowMaximized | Qt.WindowState.WindowFullScreen))


# =============================================================================
# Finestra principale: header + sidebar + pagine
# =============================================================================
class BarraIntestazione(QWidget):
    """Header esistente (titolo + stato seriale), reso trascinabile in
    modalità senza bordo delegando al window manager di Windows
    (startSystemMove) — nessun tracking manuale del mouse."""

    def mousePressEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton
                and getattr(config, "WINDOW_BORDER", "nativo") == "senza_bordo"):
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemMove()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if getattr(config, "WINDOW_BORDER", "nativo") == "senza_bordo":
            finestra = self.window()
            if _e_ingrandita(finestra):
                finestra.showNormal()
            else:
                finestra.showMaximized()
            return
        super().mouseDoubleClickEvent(event)


class GrippoRidimensionamento(QWidget):
    """Zona sottile ai bordi/angoli della finestra per ridimensionare in
    modalità senza bordo (che perde il ridimensionamento nativo trascinando
    i bordi) — delega a startSystemResize, nessun tracking manuale."""

    def __init__(self, bordi: "Qt.Edge", cursore: Qt.CursorShape, parent=None):
        super().__init__(parent)
        self._bordi = bordi
        self.setCursor(cursore)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemResize(self._bordi)
                return
        super().mousePressEvent(event)


class FinestraAmbientLight(QMainWindow):
    MARGINE_RESIZE = 6

    def __init__(self, stato_seriale: str = ""):
        super().__init__()
        self.setWindowTitle("Ambient Light ESP32")
        self.setStyleSheet(build_qss())

        self._bordo_senza_frame = getattr(config, "WINDOW_BORDER", "nativo") == "senza_bordo"
        if self._bordo_senza_frame:
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)

        radice = QWidget()
        radice.setObjectName("Root")
        self.setCentralWidget(radice)
        v_root = QVBoxLayout(radice)
        v_root.setContentsMargins(0, 0, 0, 0)
        v_root.setSpacing(0)

        # ---- Header bar (trascinabile in modalità senza bordo) ----
        header = BarraIntestazione()
        header.setObjectName("HeaderBar")
        h_head = QHBoxLayout(header)
        h_head.setContentsMargins(20, 12, 20, 12)
        h_head.setSpacing(12)

        if self._bordo_senza_frame:
            h_head.addLayout(self._crea_pallini_semaforo())

        titolo = QLabel("Ambient Light")
        titolo.setObjectName("AppTitle")
        h_head.addWidget(titolo)
        h_head.addStretch()
        self.pill_stato = StatusPill()
        h_head.addWidget(self.pill_stato)
        v_root.addWidget(header)

        # ---- Corpo: sidebar + stack ----
        corpo = QWidget()
        h_corpo = QHBoxLayout(corpo)
        h_corpo.setContentsMargins(0, 0, 0, 0)
        h_corpo.setSpacing(0)

        self.sidebar = Sidebar()
        h_corpo.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        h_corpo.addWidget(self.stack, 1)

        self.tab_preview      = TabPreview()
        self.tab_impostazioni = TabImpostazioni()

        self.stack.addWidget(self.tab_preview)
        self.stack.addWidget(self.tab_impostazioni.pagina_calibrazione)
        self.stack.addWidget(self.tab_impostazioni.pagina_parametri)
        self.stack.addWidget(self.tab_impostazioni.pagina_profili)
        self.stack.addWidget(self.tab_impostazioni.pagina_colore)
        self.stack.addWidget(self.tab_impostazioni.pagina_aspetto)

        self.sidebar.sezione_cambiata.connect(self.stack.setCurrentIndex)

        v_root.addWidget(corpo, 1)

        self.aggiorna_stato_seriale(stato_seriale)

        self._grippi: list[GrippoRidimensionamento] = []
        if self._bordo_senza_frame:
            self._crea_grippi_resize()

        self.resize(1040, 720)
        self._centra_su_primario()

    def _crea_pallini_semaforo(self) -> QHBoxLayout:
        """I 3 pallini stile macOS — chiudi/minimizza/massimizza. Sostituiscono
        i controlli nativi persi con FramelessWindowHint."""
        layout = QHBoxLayout()
        layout.setSpacing(8)

        def pallino(colore: str, on_click) -> QPushButton:
            b = QPushButton()
            b.setFixedSize(13, 13)
            b.setStyleSheet(
                f"QPushButton {{ background: {colore}; border: none; border-radius: 6px; }}"
                f"QPushButton:hover {{ background: {colore}; border: 1px solid rgba(0,0,0,80); }}"
            )
            b.clicked.connect(on_click)
            return b

        btn_chiudi = pallino("#ff5f57", self.close)
        btn_min    = pallino("#febc2e", self.showMinimized)
        btn_max    = pallino("#28c840", self._toggle_massimizza)

        layout.addWidget(btn_chiudi)
        layout.addWidget(btn_min)
        layout.addWidget(btn_max)
        return layout

    def _toggle_massimizza(self):
        if _e_ingrandita(self):
            self.showNormal()
        else:
            self.showMaximized()

    def _crea_grippi_resize(self):
        """8 zone invisibili ai bordi/angoli — la modalità senza bordo perde
        il ridimensionamento nativo trascinando i margini della finestra."""
        E, C = Qt.Edge, Qt.CursorShape
        specifiche = [
            (E.TopEdge, C.SizeVerCursor),
            (E.BottomEdge, C.SizeVerCursor),
            (E.LeftEdge, C.SizeHorCursor),
            (E.RightEdge, C.SizeHorCursor),
            (E.TopEdge | E.LeftEdge, C.SizeFDiagCursor),
            (E.TopEdge | E.RightEdge, C.SizeBDiagCursor),
            (E.BottomEdge | E.LeftEdge, C.SizeBDiagCursor),
            (E.BottomEdge | E.RightEdge, C.SizeFDiagCursor),
        ]
        for bordi, cursore in specifiche:
            grippo = GrippoRidimensionamento(bordi, cursore, self)
            grippo.raise_()
            self._grippi.append(grippo)
        self._posiziona_grippi()

    def _posiziona_grippi(self):
        if not self._grippi:
            return
        m = self.MARGINE_RESIZE
        w, h = self.width(), self.height()
        top, bottom, left, right, tl, tr, bl, br = self._grippi
        top.setGeometry(m, 0, max(0, w - 2 * m), m)
        bottom.setGeometry(m, h - m, max(0, w - 2 * m), m)
        left.setGeometry(0, m, m, max(0, h - 2 * m))
        right.setGeometry(w - m, m, m, max(0, h - 2 * m))
        tl.setGeometry(0, 0, m, m)
        tr.setGeometry(w - m, 0, m, m)
        bl.setGeometry(0, h - m, m, m)
        br.setGeometry(w - m, h - m, m, m)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._posiziona_grippi()

    def _centra_su_primario(self):
        from PyQt6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()      # area utile (esclude taskbar)
        fg   = self.frameGeometry()
        fg.moveCenter(area.center())
        self.move(fg.topLeft())

    def aggiorna_colori(self, colori: list):
        self.tab_preview.aggiorna_colori(colori)

    def aggiorna_stato_seriale(self, stato: str):
        connesso = stato.startswith("Connesso")
        self.pill_stato.imposta(stato, connesso)

    def aggiorna_stats(self, stats: dict):
        self.tab_preview.aggiorna_stats(stats)

    def closeEvent(self, event):
        if getattr(config, "TRAY_ICON_ENABLED", False):
            event.ignore()
            self.hide()
        else:
            event.accept()
