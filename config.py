# =============================================================================
# config.py
# =============================================================================

LED_TOP    = 17
LED_BOTTOM = 17
LED_LEFT   = 13
LED_RIGHT  = 13
LED_TOTAL  = LED_TOP + LED_RIGHT + LED_BOTTOM + LED_LEFT  # 60

# Indice del monitor da catturare (0 = principale). Usato come output_idx di
# dxcam e come sct.monitors[MONITOR_INDEX + 1] nel fallback mss.
MONITOR_INDEX = 0

SERIAL_PORT = "COM4"
BAUD_RATE   = 460800  # 115200 limita a 62fps — NON cambiare

# Metodo di campionamento:
#   "originale" = bande spesse e interne (SAMPLE_DEPTH_RATIO / SAMPLE_OFFSET_RATIO),
#                 media dei soli pixel più luminosi di ogni zona
#   "aree"      = ogni LED ha un proprio rettangolo sottile a filo bordo
#                 (AREA_*), media di TUTTI i suoi pixel (vedi
#                 _campiona_aree in utils.py)
SAMPLING_MODE = "originale"
AREA_DEPTH_H    = 0.08   # altezza delle bande sopra/sotto (frazione dello schermo)
AREA_DEPTH_V    = 0.05   # larghezza delle bande laterali
AREA_OVERLAP    = 0.0    # sovrapposizione tra LED adiacenti (frazione della lunghezza del lato)
AREA_EDGE_GAP   = 0.0    # spazio non campionato agli estremi di ogni lato
# Forma delle aree della modalità "aree":
#   "segmento" = ogni LED campiona tutto il suo tratto di lato
#   "quadrato" = ogni LED campiona un quadrato di lato fisso AREA_TILE, centrato
#                sul suo tratto e a filo bordo (indipendente dal passo dei LED:
#                più piccolo = più dettaglio locale, ma lascia zone non campionate)
AREA_FORMA      = "segmento"
AREA_TILE       = 0.08   # lato del quadrato, in frazione dell'altezza dello schermo

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

# Media dei pixel di ogni zona in luce lineare invece che sui
# valori sRGB codificati: una zona metà bianca/metà nera rende ~188 invece di
# ~128. False = comportamento precedente (per confronto A/B).
LINEAR_AVERAGING = True

# Limite di potenza: frazione (0-1] della corrente massima della strip
# (tutti i LED a bianco pieno = 1.0). Se la somma dei canali supera il budget
# l'intero frame viene scalato. 1.0 = off.
# 60 WS2812 a bianco pieno assorbono ~3.6A: imposta in base al tuo alimentatore.
POWER_LIMIT = 1.0

# Tipo di transizione tra un frame e il successivo (vedi ColorSmoother):
#   "esponenziale" = attacco rapido + decadimento morbido (cattura i lampi)
#   "molla"        = molla smorzata in YUV, simmetrica
SMOOTHING_MODE = "esponenziale"

# Limite di variazione della luminanza di ogni LED, in frazioni di fondo scala
# al SECONDO (indipendente dal framerate). 0 = disattivato. Es. 2.0 = un LED
# impiega almeno 0.5s per andare da nero a bianco. Attenua i lampi improvvisi;
# lo snap sui tagli di scena (SNAP_THRESHOLD) lo scavalca.
Y_LIMIT = 0.0

GAMMA            = 2.2
SOGLIA_MINIMA    = 10
SATURATION_BOOST = 1.1

TARGET_FPS = 300

# Ritmo massimo del loop di cattura (GPU->CPU), indipendente dal refresh rate
# nativo del monitor e da TARGET_FPS (che è solo il refresh della GUI/preview).
# Misurato: il costo di catturare un frame domina nettamente sul calcolo colori
# (~5ms vs ~1.7ms), e la CPU usata è quasi proporzionale a quanti frame/sec si
# catturano davvero (144fps -> 235% CPU, 60fps -> 153%, 30fps -> 65%). Un
# ambilight non ha bisogno di più di 30-60fps di cattura per sembrare fluido:
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
# Luminanza (0-255) sotto cui un pixel conta come "nero" per le barre. Separata
# da SOGLIA_MINIMA: i neri dei video a gamma limitata valgono ~16 (più rumore di
# compressione), quindi con 10 la barra non verrebbe riconosciuta.
BLACKBAR_SOGLIA     = 20

# Color correction matrix 3x3 per bilanciare il bianco reale della strip LED
# (le WS2812 spesso rendono il bianco leggermente sbilanciato verso il blu o
# il verde rispetto a quello che vede lo schermo). Identità = nessun effetto.
# out[c] = sum_k COLOR_MATRIX[c][k] * in[k]  (righe/colonne in ordine R,G,B)
COLOR_MATRIX = [
    [1.0, 0.0, 0.0],
    [0.0, 1.0, 0.0],
    [0.0, 0.0, 1.0],
]

# Guadagni R,G,B della calibrazione del bianco della strip (0.3-1.0). Sono una
# proprietà dell'HARDWARE, non del preset: vivono in calibrazione.json
# (presets.py) e si applicano SEMPRE, dopo COLOR_MATRIX. Agiscono sul valore
# sRGB prima della gamma: un guadagno g riduce la luce emessa di g^GAMMA
# (0.90 -> ~-21% con gamma 2.2), con lo stesso rapporto a ogni livello di grigio.
WHITE_GAINS = [1.0, 1.0, 1.0]

# ---------------------------------------------------------------------------
# Aspetto — persistiti in impostazioni_app.json (presets.py), non nei preset
# ambilight: sono preferenze dell'app, non tuning del segnale colore.
# Tema, colore accento e tipo di bordo richiedono un riavvio per applicarsi
# (vedi TabImpostazioni._pagina_aspetto in ui.py per il perché).
# ---------------------------------------------------------------------------
THEME             = "scuro"          # "scuro" | "chiaro"
ACCENT_MODE       = "sistema"        # "sistema" | "personalizzato"
ACCENT_CUSTOM_HEX = "#5b9df6"        # usato solo se ACCENT_MODE == "personalizzato"
WINDOW_BORDER     = "nativo"         # "nativo" | "senza_bordo"
TRAY_ICON_ENABLED = False