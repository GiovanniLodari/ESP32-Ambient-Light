# =============================================================================
# presets.py  —  Salvataggio / caricamento preset su file JSON
# =============================================================================

import json
import os
import time
import config

PRESETS_FILE     = "presets.json"
LAST_PRESET_FILE = ".last_preset"
APP_MAP_FILE     = "app_profiles.json"
APP_SETTINGS_FILE = "impostazioni_app.json"

# Chiavi di config.py che sono preferenze di aspetto dell'app, non tuning del
# segnale colore — persistite separatamente dai preset ambient light.
APP_SETTINGS_KEYS = [
    "THEME",
    "ACCENT_MODE",
    "ACCENT_CUSTOM_HEX",
    "WINDOW_BORDER",
    "TRAY_ICON_ENABLED",
]

# Profili di default creati al primo avvio se non esistono già (l'utente può
# ritararli e risalvarli con lo stesso nome — non vengono più ricreati una
# volta presenti in presets.json).
PROFILI_DEFAULT = {
    "Film": {
        "SMOOTHING_FACTOR": 0.60,
        "SNAP_THRESHOLD":   200,   # basso (60) vanificherebbe lo smoothing quasi sempre
        "TARGET_FPS":       60,
    },
    "Gaming": {
        "SMOOTHING_FACTOR": 0.15,
        "SNAP_THRESHOLD":   120,
        "TARGET_FPS":       240,
    },
}

# Tutti i parametri che vengono salvati in un preset
PARAM_KEYS = [
    "SAMPLE_DEPTH_RATIO",
    "SAMPLE_OFFSET_RATIO",
    "GAMMA",
    "SATURATION_BOOST",
    "SOGLIA_MINIMA",
    "SMOOTHING_FACTOR",
    "SNAP_THRESHOLD",
    "TARGET_FPS",
    "COLOR_MATRIX",
]


# ---------------------------------------------------------------------------
# I/O JSON interno
# ---------------------------------------------------------------------------

def _leggi(percorso: str = PRESETS_FILE) -> dict:
    if not os.path.exists(percorso):
        return {}
    try:
        with open(percorso, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[Presets] Errore lettura {percorso}: {e}")
        return {}


def _scrivi(dati: dict, percorso: str = PRESETS_FILE):
    try:
        with open(percorso, "w", encoding="utf-8") as f:
            json.dump(dati, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[Presets] Errore scrittura {percorso}: {e}")


# ---------------------------------------------------------------------------
# API pubblica
# ---------------------------------------------------------------------------

def nomi() -> list:
    """Restituisce la lista dei nomi dei preset salvati, ordinata."""
    return sorted(_leggi().keys())


def salva(nome: str):
    """Salva la configurazione corrente come preset con il nome dato."""
    dati = _leggi()
    dati[nome] = {
        "params":  {k: getattr(config, k) for k in PARAM_KEYS if hasattr(config, k)},
        "salvato": time.strftime("%Y-%m-%d %H:%M"),
    }
    _scrivi(dati)
    print(f"[Presets] Salvato: '{nome}'")


def carica(nome: str) -> dict | None:
    """Restituisce il dict dei parametri del preset, o None se non esiste."""
    entry = _leggi().get(nome)
    if entry is None:
        print(f"[Presets] Preset non trovato: '{nome}'")
        return None
    return entry["params"]


def elimina(nome: str):
    """Rimuove un preset dal file."""
    dati = _leggi()
    if nome in dati:
        del dati[nome]
        _scrivi(dati)
        print(f"[Presets] Eliminato: '{nome}'")


def applica_a_config(params: dict):
    """Scrive i valori del preset in config (in memoria)."""
    for k, v in params.items():
        if hasattr(config, k):
            setattr(config, k, v)


# ---------------------------------------------------------------------------
# Memoria "ultimo preset usato" (per auto-caricamento all'avvio)
# ---------------------------------------------------------------------------

def salva_ultimo(nome: str):
    try:
        with open(LAST_PRESET_FILE, "w", encoding="utf-8") as f:
            f.write(nome)
    except Exception:
        pass


def carica_ultimo() -> str | None:
    try:
        with open(LAST_PRESET_FILE, encoding="utf-8") as f:
            return f.read().strip() or None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Profili di default (Film / Gaming)
# ---------------------------------------------------------------------------

def assicura_profili_default():
    """Crea i preset 'Film' e 'Gaming' se non esistono già (non li sovrascrive
    mai — una volta che l'utente li ritara e risalva, restano suoi)."""
    dati = _leggi()
    cambiato = False
    for nome, params in PROFILI_DEFAULT.items():
        if nome not in dati:
            dati[nome] = {
                "params":  dict(params),
                "salvato": time.strftime("%Y-%m-%d %H:%M"),
            }
            cambiato = True
    if cambiato:
        _scrivi(dati)
        print(f"[Presets] Profili di default creati: {list(PROFILI_DEFAULT.keys())}")


# ---------------------------------------------------------------------------
# Mappatura app (processo in primo piano) → nome preset
# ---------------------------------------------------------------------------

def mappa_app_leggi() -> dict:
    """Restituisce {'nome_processo.exe': 'nome_preset', ...}."""
    return _leggi(APP_MAP_FILE)


def mappa_app_imposta(exe: str, nome_preset: str):
    mappa = mappa_app_leggi()
    mappa[exe] = nome_preset
    _scrivi(mappa, APP_MAP_FILE)


def mappa_app_rimuovi(exe: str):
    mappa = mappa_app_leggi()
    if exe in mappa:
        del mappa[exe]
        _scrivi(mappa, APP_MAP_FILE)


# ---------------------------------------------------------------------------
# Impostazioni d'aspetto (tema, colore accento, bordo finestra, tray) —
# separate dai preset ambient light: sono preferenze dell'app, non del segnale.
# ---------------------------------------------------------------------------

def impostazioni_app_leggi() -> dict:
    return _leggi(APP_SETTINGS_FILE)


def impostazioni_app_scrivi(valori: dict):
    dati = impostazioni_app_leggi()
    dati.update(valori)
    _scrivi(dati, APP_SETTINGS_FILE)


def impostazioni_app_applica_a_config():
    """Applica le impostazioni d'aspetto salvate a config, se presenti
    (chiamare all'avvio, prima di costruire la UI)."""
    dati = impostazioni_app_leggi()
    for k in APP_SETTINGS_KEYS:
        if k in dati and hasattr(config, k):
            setattr(config, k, dati[k])