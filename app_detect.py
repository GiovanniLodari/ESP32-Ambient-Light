# =============================================================================
# app_detect.py - Rilevamento del processo in primo piano (per switch profilo)
# =============================================================================

try:
    import win32gui
    import win32process
    import psutil
    _WIN32_OK = True
except ImportError:
    _WIN32_OK = False
    print("[AppDetect] pywin32 non trovato — switch automatico per app disattivato")


def processo_primo_piano() -> str | None:
    """Nome dell'eseguibile (es. 'csgo.exe') della finestra in primo piano, o None."""
    if not _WIN32_OK:
        return None
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return None
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return psutil.Process(pid).name()
    except Exception:
        return None
