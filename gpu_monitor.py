# =============================================================================
# gpu_monitor.py - VRAM dedicata usata dal PROCESSO corrente (quella che Task
# Manager chiama "Dedicated GPU memory"), letta dai contatori prestazionali
# di Windows — funziona con qualunque GPU, non solo NVIDIA.
# =============================================================================

import os
import threading

try:
    import win32pdh
    _WIN32PDH_OK = True
except ImportError:
    _WIN32PDH_OK = False
    print("[GPU] pywin32 non trovato — stat VRAM disattivata")

POLL_INTERVAL_S = 2.0
CONTATORE = r"\GPU Process Memory(*)\Dedicated Usage"


class VRAMMonitor:
    """Polling in background della VRAM dedicata usata da QUESTO processo
    (somma su tutti gli adattatori/LUID, come mostra Task Manager).

    Gira in un thread dedicato: enumerare ed interrogare i contatori PDH ad
    ogni frame sul thread della GUI introdurrebbe latenza inutile — qui viene
    ricalcolata ogni 2s, in linea con le altre statistiche (CPU/RAM)."""

    def __init__(self):
        self.used_mb     = 0.0
        self.disponibile = _WIN32PDH_OK
        self._pid  = os.getpid()
        self._stop = threading.Event()
        if self.disponibile:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def _loop(self):
        pattern = f"pid_{self._pid}_"
        while not self._stop.is_set():
            try:
                query = win32pdh.OpenQuery()
                try:
                    percorsi = win32pdh.ExpandCounterPath(CONTATORE)
                    handles = [win32pdh.AddCounter(query, p)
                               for p in percorsi if pattern in p]
                    if handles:
                        win32pdh.CollectQueryData(query)
                        totale = sum(
                            win32pdh.GetFormattedCounterValue(h, win32pdh.PDH_FMT_LARGE)[1]
                            for h in handles
                        )
                        self.used_mb = totale / (1024 * 1024)
                finally:
                    win32pdh.CloseQuery(query)
            except Exception:
                pass
            self._stop.wait(POLL_INTERVAL_S)

    def stop(self):
        self._stop.set()
