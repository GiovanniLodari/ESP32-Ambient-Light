# =============================================================================
# main.py - Controller principale Ambient Light ESP32
# =============================================================================

import sys
import time

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor

import config
import presets

# Va applicato PRIMA di importare ui: il modulo ui.py calcola la palette
# tema/accento una sola volta, leggendo config.THEME/ACCENT_MODE al momento
# dell'import. Se questa chiamata avvenisse dopo (es. in __init__), ui.py
# vedrebbe ancora i default di config.py invece dei valori salvati.
presets.impostazioni_app_applica_a_config()

import app_detect
from gpu_monitor import VRAMMonitor
from utils import ScreenProcessor, _build_gamma_table
from serial_comm import SerialManager
from ui import FinestraAmbientLight, ACCENT

APP_POLL_MS = 1500  # intervallo di controllo del processo in primo piano

COLORI_TEST = {
    "top":    (180, 0,   0  ),
    "right":  (0,   180, 0  ),
    "bottom": (0,   0,   180),
    "left":   (180, 180, 0  ),
}


class ControllerAmbientLight:

    def __init__(self):
        self.app = QApplication(sys.argv)
        # Lo stile nativo di Windows ("windowsvista") disegna certi elementi
        # (popup dei combobox, hover, checkbox) con i colori di sistema anche
        # in presenza di un QSS. "Fusion" è disegnato interamente da Qt e
        # rispetta sempre lo stylesheet dell'app.
        self.app.setStyle("Fusion")
        self.in_test   = False
        self.lati_test = {"top": False, "right": False, "bottom": False, "left": False}

        self._tick_count = 0
        self._fps_timer  = time.time()
        self._fps_ui     = 0.0

        # Inizializza psutil.
        # La prima chiamata a cpu_percent() restituisce SEMPRE 0.0 (by design):
        # ha bisogno di due misurazioni per calcolare la delta temporale.
        # Chiamiamo subito interval=None per "armare" il contatore interno,
        # poi scartiamo il risultato.
        if _PSUTIL:
            self._psutil_proc = psutil.Process()
            self._psutil_proc.cpu_percent()   # prima chiamata sacrificale → 0.0, scartata
        else:
            self._psutil_proc = None

        # Pre-popola la cache così la GUI mostra 0 invece di "—" al primo avvio
        self._stats_cache: dict = {"cpu": 0.0, "ram": 0.0, "vram": 0.0}
        self._vram = VRAMMonitor()

        self.processor = ScreenProcessor()
        info = self.processor.get_info_monitor()
        hz = f" @ {info['refresh_hz']}Hz" if info.get('refresh_hz') else ""
        print(f"[Main] Monitor: {info['larghezza']}x{info['altezza']}{hz}")

        self.seriale = SerialManager()
        self.processor.set_seriale(self.seriale)
        self._verifica_num_led()

        self.finestra = FinestraAmbientLight(stato_seriale=self.seriale.stato)

        # ---- Collega segnali ----
        imp = self.finestra.tab_impostazioni
        imp.depth_cambiato.connect(self._on_depth)
        imp.offset_cambiato.connect(self._on_offset)
        imp.gamma_cambiato.connect(self._on_gamma)
        imp.soglia_cambiata.connect(self._on_soglia)
        imp.smoothing_cambiato.connect(self._on_smoothing)
        imp.snap_cambiato.connect(self._on_snap)
        imp.fps_cambiato.connect(self._on_fps)
        imp.saturazione_cambiata.connect(self._on_saturazione)
        imp.blackbar_cambiato.connect(self._on_blackbar)
        imp.color_matrix_cambiata.connect(self._on_color_matrix)
        imp.lati_test_cambiati.connect(self._on_lati_test)
        imp.modalita_test.connect(self._on_modalita_test)
        imp.preset_salvato.connect(self._on_preset_salva)
        imp.preset_caricato.connect(self._on_preset_carica)
        imp.preset_eliminato.connect(self._on_preset_elimina)
        imp.app_mapping_aggiunta.connect(self._on_app_mapping_aggiunta)
        imp.app_mapping_rimossa.connect(self._on_app_mapping_rimossa)
        imp.tray_cambiato.connect(self._on_tray_cambiato)
        imp.bordo_finestra_cambiato.connect(self._on_bordo_finestra)
        imp.tema_cambiato.connect(self._on_tema)
        imp.accent_mode_cambiato.connect(self._on_accent_mode)
        imp.accent_custom_cambiato.connect(self._on_accent_custom)

        # Il timer deve esistere prima di caricare il preset: applicarlo può
        # emettere fps_cambiato (cambio indice combo FPS), che chiama _on_fps
        # e usa self.timer.
        self.timer = QTimer()
        self.timer.timeout.connect(self._tick)
        self.timer.start(max(1, int(1000 / config.TARGET_FPS)))

        # Stato switch automatico per app — creato prima di avviare il polling,
        # stesso motivo del timer sopra.
        self._ultima_app         = None
        self._profilo_auto_attivo = None
        self.app_timer = QTimer()
        self.app_timer.timeout.connect(self._controlla_app_attiva)
        self.app_timer.start(APP_POLL_MS)

        self.finestra.show()
        presets.assicura_profili_default()
        self._carica_preset_iniziale()
        self.finestra.tab_impostazioni.aggiorna_mappe_app(presets.mappa_app_leggi())

        self._tray = None
        self._on_tray_cambiato(config.TRAY_ICON_ENABLED)

    # =========================================================================
    # Slot parametri
    # =========================================================================

    def _on_depth(self, val: float):
        config.SAMPLE_DEPTH_RATIO = val
        self.finestra.tab_impostazioni.aggiorna_depth_anteprima(val)

    def _on_offset(self, val: float):
        config.SAMPLE_OFFSET_RATIO = val
        self.finestra.tab_impostazioni.aggiorna_offset_anteprima(val)

    def _on_gamma(self, val: float):
        config.GAMMA = val
        self._ricostruisci_gamma()

    def _on_soglia(self, val: int):
        config.SOGLIA_MINIMA = val

    def _on_smoothing(self, val: float):
        config.SMOOTHING_FACTOR = val

    def _on_snap(self, val: int):
        config.SNAP_THRESHOLD = val

    def _on_fps(self, val: int):
        config.TARGET_FPS = val
        self.timer.setInterval(max(1, int(1000 / val)))

    def _on_saturazione(self, val: float):
        config.SATURATION_BOOST = val

    def _on_blackbar(self, attivo: bool):
        config.BLACKBAR_DETECTION = attivo

    def _on_color_matrix(self, matrice: list):
        # Assegnazione atomica dell'intero oggetto: il thread di cattura legge
        # config.COLOR_MATRIX senza lock, quindi mai mutare in-place.
        config.COLOR_MATRIX = matrice

    def _on_lati_test(self, lati: dict):
        self.lati_test = lati

    def _on_modalita_test(self, attivo: bool):
        self.in_test = attivo
        if not attivo:
            self.processor.smoother.reset()
            self.processor.barre.reset()

    # =========================================================================
    # Slot preset
    # =========================================================================

    def _carica_preset_iniziale(self):
        nome  = presets.carica_ultimo()
        tutti = presets.nomi()
        if nome and nome in tutti:
            params = presets.carica(nome)
            if params:
                presets.applica_a_config(params)
                self.finestra.tab_impostazioni.applica_valori(params)
                self._ricostruisci_gamma()
                print(f"[Preset] Auto-caricato: '{nome}'")
        self.finestra.tab_impostazioni.aggiorna_lista_preset(tutti, nome or "")

    def _on_preset_salva(self, nome: str):
        presets.salva(nome)
        presets.salva_ultimo(nome)
        self.finestra.tab_impostazioni.aggiorna_lista_preset(presets.nomi(), nome)

    def _on_preset_carica(self, nome: str):
        params = presets.carica(nome)
        if params:
            presets.applica_a_config(params)
            presets.salva_ultimo(nome)
            self.finestra.tab_impostazioni.applica_valori(params)
            self._ricostruisci_gamma()
            self.processor.smoother.reset()
            self.processor.barre.reset()

    def _on_preset_elimina(self, nome: str):
        presets.elimina(nome)
        self.finestra.tab_impostazioni.aggiorna_lista_preset(presets.nomi())

    def _ricostruisci_gamma(self):
        self.processor._gamma = _build_gamma_table(config.GAMMA)

    def _verifica_num_led(self):
        """Chiede al firmware quanti LED ha configurati e segnala se non
        corrisponde a config.LED_TOTAL — es. hai cambiato la lunghezza della
        strip ma non aggiornato LED_TOP/BOTTOM/LEFT/RIGHT in config.py."""
        rilevati = self.seriale.interroga_num_led()
        if rilevati is None:
            if self.seriale.connesso:
                print("[Seriale] Firmware non risponde alla query LED "
                      "(versione precedente senza questo comando?)")
            return
        if rilevati != config.LED_TOTAL:
            print(f"[Seriale] ATTENZIONE: il firmware ha {rilevati} LED configurati, "
                  f"ma config.py ne assume {config.LED_TOTAL} "
                  f"(LED_TOP+LED_BOTTOM+LED_LEFT+LED_RIGHT) — controlla config.py.")
        else:
            print(f"[Seriale] Numero LED verificato: {rilevati} (corrisponde a config.py)")

    # =========================================================================
    # System tray
    # =========================================================================

    def _crea_icona_tray(self) -> QIcon:
        """Genera un'icona a runtime (cerchio pieno nel colore accento) —
        niente file .ico esterno da aggiungere al repo."""
        dim = 64
        pix = QPixmap(dim, dim)
        pix.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(ACCENT))
        painter.drawEllipse(4, 4, dim - 8, dim - 8)
        painter.end()
        return QIcon(pix)

    def _on_tray_cambiato(self, attivo: bool):
        config.TRAY_ICON_ENABLED = attivo
        presets.impostazioni_app_scrivi({"TRAY_ICON_ENABLED": attivo})

        if attivo and self._tray is None:
            self._tray = QSystemTrayIcon(self._crea_icona_tray())
            self._tray.setToolTip("Ambient Light ESP32")
            menu = QMenu()
            azione_mostra = menu.addAction("Mostra")
            azione_mostra.triggered.connect(self._mostra_finestra)
            azione_esci = menu.addAction("Esci")
            azione_esci.triggered.connect(self.app.quit)
            self._tray.setContextMenu(menu)
            self._tray.activated.connect(self._on_tray_activated)
            self._tray.show()
        elif not attivo and self._tray is not None:
            self._tray.hide()
            self._tray.deleteLater()
            self._tray = None

    def _on_bordo_finestra(self, valore: str):
        # Solo persistenza — richiede riavvio per applicarsi (i flag di
        # finestra vanno impostati prima di show(), vedi FinestraAmbientLight).
        config.WINDOW_BORDER = valore
        presets.impostazioni_app_scrivi({"WINDOW_BORDER": valore})

    def _on_tema(self, valore: str):
        # Solo persistenza — richiede riavvio: la palette viene calcolata una
        # sola volta all'import di ui.py (vedi TEMI in ui.py).
        config.THEME = valore
        presets.impostazioni_app_scrivi({"THEME": valore})

    def _on_accent_mode(self, valore: str):
        config.ACCENT_MODE = valore
        presets.impostazioni_app_scrivi({"ACCENT_MODE": valore})

    def _on_accent_custom(self, valore: str):
        config.ACCENT_MODE = "personalizzato"
        config.ACCENT_CUSTOM_HEX = valore
        presets.impostazioni_app_scrivi({"ACCENT_MODE": "personalizzato", "ACCENT_CUSTOM_HEX": valore})

    def _mostra_finestra(self):
        self.finestra.show()
        self.finestra.activateWindow()

    def _on_tray_activated(self, motivo):
        if motivo == QSystemTrayIcon.ActivationReason.Trigger:
            if self.finestra.isVisible():
                self.finestra.hide()
            else:
                self._mostra_finestra()

    # =========================================================================
    # Slot profili automatici per app
    # =========================================================================

    def _on_app_mapping_aggiunta(self, exe: str, nome: str):
        presets.mappa_app_imposta(exe, nome)
        self.finestra.tab_impostazioni.aggiorna_mappe_app(presets.mappa_app_leggi())

    def _on_app_mapping_rimossa(self, exe: str):
        presets.mappa_app_rimuovi(exe)
        self.finestra.tab_impostazioni.aggiorna_mappe_app(presets.mappa_app_leggi())

    def _controlla_app_attiva(self):
        exe = app_detect.processo_primo_piano()
        if not exe or exe == self._ultima_app:
            return
        self._ultima_app = exe
        nome = presets.mappa_app_leggi().get(exe)
        if nome and nome != self._profilo_auto_attivo:
            self._applica_profilo_auto(nome, exe)

    def _applica_profilo_auto(self, nome: str, exe: str):
        """Come _on_preset_carica, ma non tocca 'ultimo preset usato': lo switch
        automatico non deve alterare cosa viene ricaricato al prossimo avvio."""
        params = presets.carica(nome)
        if params:
            presets.applica_a_config(params)
            self.finestra.tab_impostazioni.applica_valori(params)
            self._ricostruisci_gamma()
            self.processor.smoother.reset()
            self.processor.barre.reset()
            self._profilo_auto_attivo = nome
            self.finestra.tab_impostazioni.aggiorna_stato_auto(f"{nome} ({exe})")
            print(f"[AppDetect] Profilo '{nome}' applicato per '{exe}'")

    # =========================================================================
    # Tick principale  — NON stampa nulla: le stats vanno solo alla GUI
    # =========================================================================

    def _tick(self):
        self._tick_count += 1
        now     = time.time()
        elapsed = now - self._fps_timer

        # Aggiorna fps UI e letture psutil ogni 2 secondi (operazioni costose)
        if elapsed >= 2.0:
            self._fps_ui     = self._tick_count / elapsed
            self._tick_count = 0
            self._fps_timer  = now

            if _PSUTIL and self._psutil_proc:
                try:
                    # interval=None: usa la delta dall'ultima chiamata, non blocca
                    self._stats_cache["cpu"] = self._psutil_proc.cpu_percent(interval=None)
                    self._stats_cache["ram"] = (
                        self._psutil_proc.memory_info().rss / 1024 / 1024
                    )
                except Exception:
                    pass

            # VRAMMonitor gira già in un thread suo — qui si legge solo il
            # valore già calcolato, nessuna chiamata bloccante.
            self._stats_cache["vram"] = self._vram.used_mb

        try:
            stats = self.processor.get_stats()
            stats["fps_ui"] = self._fps_ui
            stats.update(self._stats_cache)

            if self.in_test:
                colori = self._colori_test()
                self.finestra.aggiorna_colori(colori)
                self.seriale.invia_colori(colori)
            else:
                colori = self.processor.calcola_colori()
                self.finestra.aggiorna_colori(colori)

            self.finestra.aggiorna_stats(stats)
            self.finestra.aggiorna_stato_seriale(self.seriale.stato)

        except Exception as e:
            print(f"[Main] Errore tick: {e}")

    def _colori_test(self) -> list:
        colori = []
        for lato, count in [("right",  config.LED_RIGHT),
                             ("top",    config.LED_TOP),
                             ("left",   config.LED_LEFT),
                             ("bottom", config.LED_BOTTOM)]:
            c = COLORI_TEST[lato] if self.lati_test.get(lato) else (0, 0, 0)
            colori += [c] * count
        return colori

    # =========================================================================
    # Avvio / spegnimento
    # =========================================================================

    def esegui(self):
        codice = self.app.exec()
        self.timer.stop()
        self.app_timer.stop()
        self._vram.stop()
        if self._tray is not None:
            self._tray.hide()
        self.processor.stop()
        self.seriale.chiudi()
        return codice


def main():
    print("=" * 50)
    print("  Ambient Light ESP32")
    print("=" * 50)
    ctrl = ControllerAmbientLight()
    sys.exit(ctrl.esegui())


if __name__ == "__main__":
    main()