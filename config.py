# =============================================================================
# config.py
# =============================================================================

LED_TOP    = 17
LED_BOTTOM = 17
LED_LEFT   = 13
LED_RIGHT  = 13
LED_TOTAL  = LED_TOP + LED_RIGHT + LED_BOTTOM + LED_LEFT  # 60

SERIAL_PORT = "COM4"
BAUD_RATE   = 460800  # 115200 limita a 62fps — NON cambiare

SAMPLE_DEPTH_RATIO  = 0.20
SAMPLE_DEPTH_MIN    = 40
SAMPLE_OFFSET_RATIO = 0.12

# Smoothing: 0.0 = istantaneo (real-time), 1.0 = non si muove mai
# Con SNAP_THRESHOLD attivo, puoi alzare questo valore senza perdere reattività
# sui tagli di scena.
SMOOTHING_FACTOR = 0.40

# Delta massimo (0–255) oltre cui un LED scatta immediatamente al nuovo colore
# invece di interpolare. Gestisce i tagli di scena senza rinunciare alla fluidità.
# 0 = disabilita lo snap (comportamento originale puro).
# Attenzione: un valore troppo basso (es. 80) intercetta anche i normali cambi
# di colore a schermo, non solo i tagli di scena estremi — lo smoothing non
# scatterebbe quasi mai. 200 lascia lo snap solo per salti davvero drastici.
SNAP_THRESHOLD = 200

GAMMA            = 2.2
SOGLIA_MINIMA    = 10
SATURATION_BOOST = 1.1

TARGET_FPS = 300

# Ritmo massimo del loop di cattura (GPU->CPU), indipendente dal refresh rate
# nativo del monitor e da TARGET_FPS (che è solo il refresh della GUI/preview).
# Misurato: il costo di catturare un frame domina nettamente sul calcolo colori
# (~5ms vs ~1.7ms), e la CPU usata è quasi proporzionale a quanti frame/sec si
# catturano davvero (144fps -> 235% CPU, 60fps -> 153%, 30fps -> 65%). Un
# ambient light non ha bisogno di più di 30-60fps di cattura per sembrare fluido:
# alzarlo oltre non migliora percepibilmente la resa ma costa CPU in modo quasi
# lineare. Se il monitor ha un refresh nativo più basso di questo valore, viene
# comunque usato quello (non ha senso chiedere più fps di quanti il monitor ne produca).
CAPTURE_FPS_CAP = 60

# Rilevamento dinamico barre nere (letterbox/pillarbox): restringe il
# campionamento verso il centro del contenuto reale quando rileva barre nere
# sostenute ai bordi. BLACKBAR_MAX_RATIO limita quanto può "mangiare" per lato
# (frazione di altezza/larghezza) — oltre quel limite si assume che sia una
# scena scura, non letterbox, e i LED si spengono normalmente via SOGLIA_MINIMA.
BLACKBAR_DETECTION  = True
BLACKBAR_MAX_RATIO  = 0.20

# Color correction matrix 3x3 per bilanciare il bianco reale della strip LED
# (le WS2812 spesso rendono il bianco leggermente sbilanciato verso il blu o
# il verde rispetto a quello che vede lo schermo). Identità = nessun effetto.
# out[c] = sum_k COLOR_MATRIX[c][k] * in[k]  (righe/colonne in ordine R,G,B)
COLOR_MATRIX = [
    [1.0, 0.0, 0.0],
    [0.0, 1.0, 0.0],
    [0.0, 0.0, 1.0],
]

# ---------------------------------------------------------------------------
# Aspetto — persistiti in impostazioni_app.json (presets.py), non nei preset
# ambient light: sono preferenze dell'app, non tuning del segnale colore.
# Tema, colore accento e tipo di bordo richiedono un riavvio per applicarsi
# (vedi TabImpostazioni._pagina_aspetto in ui.py per il perché).
# ---------------------------------------------------------------------------
THEME             = "scuro"          # "scuro" | "chiaro"
ACCENT_MODE       = "sistema"        # "sistema" | "personalizzato"
ACCENT_CUSTOM_HEX = "#5b9df6"        # usato solo se ACCENT_MODE == "personalizzato"
WINDOW_BORDER     = "nativo"         # "nativo" | "senza_bordo"
TRAY_ICON_ENABLED = False