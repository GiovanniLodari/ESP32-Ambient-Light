import threading
import time
import numpy as np
import mss
import config
from config import LED_TOP, LED_BOTTOM, LED_LEFT, LED_RIGHT, LED_TOTAL

try:
    import dxcam
    _DXCAM_AVAILABLE = True
except ImportError:
    _DXCAM_AVAILABLE = False
    print("[Utils] dxcam non trovato — usa: pip install dxcam")

try:
    import win32api
    import win32con
    _WIN32_DISPLAY_OK = True
except ImportError:
    _WIN32_DISPLAY_OK = False


def _rileva_refresh_rate() -> int | None:
    """Hz del monitor corrente (Impostazioni display di Windows), o None se
    non rilevabile — usato per tarare il ritmo di cattura sul refresh reale
    invece di lasciarlo completamente scoperto."""
    if not _WIN32_DISPLAY_OK:
        return None
    try:
        s = win32api.EnumDisplaySettings(None, win32con.ENUM_CURRENT_SETTINGS)
        hz = s.DisplayFrequency
        return hz if hz and hz > 0 else None
    except Exception:
        return None


IDENTITA_COLOR_MATRIX = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]


THUMB_W, THUMB_H = 256, 144

# sRGB codificato (0-255) -> luce lineare (0-1). Serve per fare la media dei
# pixel in luce lineare (config.LINEAR_AVERAGING).
_x = np.arange(256, dtype=np.float32) / 255.0
_SRGB_TO_LIN = np.where(_x <= 0.04045, _x / 12.92,
                        ((_x + 0.055) / 1.055) ** 2.4).astype(np.float32)
del _x


def _lineare_a_srgb255(lin: np.ndarray) -> np.ndarray:
    """Luce lineare (0-1) -> sRGB codificato (0-255), in float."""
    lin = np.clip(lin, 0.0, 1.0)
    enc = np.where(lin <= 0.0031308, lin * 12.92,
                   1.055 * np.power(lin, 1 / 2.4) - 0.055)
    return (enc * 255.0).astype(np.float32)


_IDX_RIDUZIONE: dict = {}


def _riduci_a_miniatura(frame: np.ndarray) -> np.ndarray:
    """Riduce il frame a THUMB_W x THUMB_H campionando UN pixel per cella.

    Se la risoluzione è un multiplo esatto (es. 2560x1440) è una semplice
    slice, senza copia. Altrimenti (1920x1080, ultrawide, giochi che cambiano
    risoluzione) si usano indici calcolati sulla dimensione reale: la vecchia
    decimazione a passo intero + ritaglio perdeva fino al 7% di schermo a
    destra/in basso, spostando i LED di quei lati."""
    fh, fw = frame.shape[:2]
    if fh % THUMB_H == 0 and fw % THUMB_W == 0:
        return frame[::fh // THUMB_H, ::fw // THUMB_W]
    idx = _IDX_RIDUZIONE.get((fh, fw))
    if idx is None:
        ys = ((np.arange(THUMB_H) + 0.5) * fh / THUMB_H).astype(np.intp)
        xs = ((np.arange(THUMB_W) + 0.5) * fw / THUMB_W).astype(np.intp)
        idx = _IDX_RIDUZIONE[(fh, fw)] = (ys[:, None], xs[None, :])
    return frame[idx]


_RETTANGOLI_AREE: dict = {}


def _rettangoli_aree(dh: float, dv: float, overlap: float, gap: float) -> np.ndarray:
    """Rettangoli (x0, x1, y0, y1) in frazioni dell'immagine, uno per LED, nello
    stesso ordine dei LED della tua strip (RIGHT, TOP, LEFT, BOTTOM).

    Le bande hanno profondità `dh` (sopra/sotto) e `dv` (lati) a filo bordo,
    ogni LED copre un tratto del lato più l'eventuale sovrapposizione
    `overlap`, con `gap` non campionato agli estremi. Lati e bande si
    estendono fino agli angoli, quindi negli angoli le bande si
    sovrappongono."""
    chiave = (round(dh, 4), round(dv, 4), round(overlap, 4), round(gap, 4))
    r = _RETTANGOLI_AREE.get(chiave)
    if r is not None:
        return r

    gap_v = gap / 2.0
    gap_h = gap_v / (16.0 / 9.0)
    cl = lambda v: min(1.0, max(0.0, v))

    def tratti(n, g):
        passo = (1.0 - 2 * g) / n
        return [(cl(i * passo + g - overlap), cl((i + 1) * passo + g + overlap)) for i in range(n)]

    lungo_h = tratti(LED_TOP, gap_h)       # x di ogni LED sopra (stessi tratti per il sotto)
    lungo_b = tratti(LED_BOTTOM, gap_h)
    lungo_r = tratti(LED_RIGHT, gap_v)     # y di ogni LED laterale, dall'alto in basso
    lungo_l = tratti(LED_LEFT, gap_v)

    destra = [(1 - dv, 1.0, y0, y1) for (y0, y1) in lungo_r][::-1]     # il tuo ordine: dal basso in alto
    sopra  = [(x0, x1, 0.0, dh) for (x0, x1) in lungo_h][::-1]         # da destra a sinistra
    sinistra = [(0.0, dv, y0, y1) for (y0, y1) in lungo_l]             # dall'alto in basso
    sotto  = [(x0, x1, 1 - dh, 1.0) for (x0, x1) in lungo_b]           # da sinistra a destra

    r = np.array(destra + sopra + sinistra + sotto, dtype=np.float64)
    _RETTANGOLI_AREE[chiave] = r
    return r


def _lato_di_ogni_led() -> np.ndarray:
    """0=destra, 1=sopra, 2=sinistra, 3=sotto, nell'ordine dei LED."""
    return np.repeat([0, 1, 2, 3], [LED_RIGHT, LED_TOP, LED_LEFT, LED_BOTTOM])


def _rettangoli_aree_pixel(area: tuple, aspetto: float) -> np.ndarray:
    """Rettangoli (x0, x1, y0, y1) in pixel della miniatura, uno per LED.
    `area` = (x0, x1, y0, y1) del contenuto (senza barre nere); `aspetto` =
    altezza/larghezza dello schermo reale, per tenere i quadrati davvero
    quadrati in pixel anche su schermi non 16:9."""
    cx0, cx1, cy0, cy1 = area
    W, H = cx1 - cx0, cy1 - cy0
    r = _rettangoli_aree(config.AREA_DEPTH_H, config.AREA_DEPTH_V,
                             config.AREA_OVERLAP, config.AREA_EDGE_GAP)

    if config.AREA_FORMA == "quadrato":
        # lato fisso rispetto allo SCHERMO (non al contenuto): non cambia
        # quando compaiono le barre nere
        lh = min(max(1, int(round(config.AREA_TILE * THUMB_H))), H)
        lw = min(max(1, int(round(config.AREA_TILE * THUMB_W * aspetto))), W)
        cx = cx0 + (r[:, 0] + r[:, 1]) / 2.0 * W      # centro del tratto, lungo x
        cy = cy0 + (r[:, 2] + r[:, 3]) / 2.0 * H      # centro del tratto, lungo y
        x0 = np.rint(cx - lw / 2.0).astype(np.intp)
        y0 = np.rint(cy - lh / 2.0).astype(np.intp)
        lato = _lato_di_ogni_led()
        y0 = np.where(lato == 1, cy0, np.where(lato == 3, cy1 - lh, y0))   # sopra / sotto: a filo bordo
        x0 = np.where(lato == 2, cx0, np.where(lato == 0, cx1 - lw, x0))   # sinistra / destra
        x0 = np.clip(x0, cx0, cx1 - lw); y0 = np.clip(y0, cy0, cy1 - lh)
        return np.stack([x0, x0 + lw, y0, y0 + lh], axis=1)

    x0 = cx0 + np.rint(r[:, 0] * W).astype(np.intp)
    x1 = cx0 + np.rint(r[:, 1] * W).astype(np.intp)
    y0 = cy0 + np.rint(r[:, 2] * H).astype(np.intp)
    y1 = cy0 + np.rint(r[:, 3] * H).astype(np.intp)
    # almeno 1 pixel per lato, dentro l'area
    x0 = np.minimum(x0, cx1 - 1); x1 = np.clip(np.maximum(x1, x0 + 1), cx0 + 1, cx1)
    y0 = np.minimum(y0, cy1 - 1); y1 = np.clip(np.maximum(y1, y0 + 1), cy0 + 1, cy1)
    return np.stack([x0, x1, y0, y1], axis=1)


def _campiona_aree(src: np.ndarray, area: tuple, aspetto: float = 9 / 16) -> np.ndarray:
    """Media di TUTTI i pixel del rettangolo di ogni LED (nessuna selezione dei
    pixel più luminosi). `area` = contenuto senza barre nere, su cui si
    mappano le aree: l'immagine viene ritagliata al bordo rilevato. Usa una
    tabella di somme cumulate, quindi il costo non dipende dalla dimensione
    delle aree."""
    px = _rettangoli_aree_pixel(area, aspetto)
    x0, x1, y0, y1 = px[:, 0], px[:, 1], px[:, 2], px[:, 3]
    sat = np.zeros((src.shape[0] + 1, src.shape[1] + 1, 3), dtype=np.float64)
    np.cumsum(np.cumsum(src, axis=0, dtype=np.float64), axis=1, out=sat[1:, 1:])
    somma = sat[y1, x1] - sat[y0, x1] - sat[y1, x0] + sat[y0, x0]
    area_px = ((x1 - x0) * (y1 - y0))[:, None]
    return (somma / area_px).astype(np.float32)


class TemporalDither:
    """Dithering temporale con diffusione dell'errore, per recuperare la
    risoluzione persa nel passaggio a 8 bit (specie sui livelli bassi dopo la
    gamma: senza, 0-40 collassano su pochi gradini e le scene scure scattano).

    Agisce solo sui LED il cui valore sta cambiando: a segnale fermo si arrotonda
    semplicemente, così una zona costante non sfarfalla tra due livelli."""

    SOGLIA_MOTO = 0.004   # variazione per frame (livelli a 8 bit) sotto cui il LED è "fermo"

    def __init__(self, n):
        self._err  = np.zeros((n, 3), dtype=np.float32)
        self._prev = np.zeros((n, 3), dtype=np.float32)

    def applica(self, x: np.ndarray, sempre: bool = False) -> np.ndarray:
        """`sempre=True` dithera anche a segnale fermo (pattern di calibrazione:
        un grigio scuro vale ~1.5 livelli, e arrotondarlo falserebbe il rapporto
        tra i canali)."""
        x = np.clip(x, 0.0, 255.0)
        moto = (np.abs(x - self._prev) >= self.SOGLIA_MOTO).any(axis=1)[:, None] | sempre
        self._prev = x.copy()      # copia: lo smoother riusa/modifica il suo array

        v = np.where(moto, x + self._err, x)
        q = np.clip(np.floor(v + 0.5), 0, 255)
        # niente errore residuo se il LED è fermo o deve essere spento del tutto
        self._err = np.where(moto & (x > 0), v - q, 0.0).astype(np.float32)
        return q.astype(np.uint8)

    def reset(self):
        self._err[:] = 0
        self._prev[:] = 0


def _sat_boost_batch(rgb: np.ndarray, boost: float) -> np.ndarray:
    """Boost saturazione completamente vettorizzato — zero loop Python."""
    if boost == 1.0:
        return rgb
    f = rgb / 255.0
    r, g, b = f[:,0], f[:,1], f[:,2]
    cmax  = f.max(axis=1)
    cmin  = f.min(axis=1)
    delta = cmax - cmin

    s = np.where(cmax > 1e-6, delta / np.maximum(cmax, 1e-6), 0.0)
    s = np.clip(s * boost, 0.0, 1.0)
    v = cmax

    h = np.zeros(len(r), dtype=np.float32)
    mr = (cmax == r) & (delta > 1e-6)
    mg = (cmax == g) & (delta > 1e-6)
    mb = (cmax == b) & (delta > 1e-6)
    h[mr] = ((g[mr] - b[mr]) / delta[mr]) % 6
    h[mg] = (b[mg] - r[mg]) / delta[mg] + 2
    h[mb] = (r[mb] - g[mb]) / delta[mb] + 4
    h /= 6.0

    h6 = (h * 6.0) % 6.0
    i  = h6.astype(np.int32)
    ff = h6 - i
    p  = v * (1.0 - s)
    q  = v * (1.0 - ff * s)
    t  = v * (1.0 - (1.0 - ff) * s)

    ro = np.select([i==0, i==1, i==2, i==3, i==4, i==5], [v,q,p,p,t,v])
    go = np.select([i==0, i==1, i==2, i==3, i==4, i==5], [t,v,v,q,p,p])
    bo = np.select([i==0, i==1, i==2, i==3, i==4, i==5], [p,p,t,v,v,q])

    out = np.stack([ro, go, bo], axis=1)
    acromatici = s < 1e-6
    out[acromatici] = f[acromatici]
    return out * 255.0


def _applica_color_matrix(segs: np.ndarray, matrice: np.ndarray) -> np.ndarray:
    """Corregge lo sbilanciamento cromatico della strip fisica (es. bianco che
    tende al blu/verde) con una matrice 3x3: out[c] = sum_k matrice[c,k]*in[k].
    Applicata dopo il saturation boost, prima della gamma LUT — stesso ordine
    concettuale della color correction di FastLED."""
    out = segs @ matrice.T
    return np.clip(out, 0, 255)


# =============================================================================
# ColorSmoother — interpolazione adattiva con snap sui tagli di scena
# =============================================================================

# BT.709 RGB <-> YUV (Y in 0..1, U e V in -0.5..0.5): la luminanza è separata
# dal colore.
_KR, _KB = 0.2126, 0.0722
_KG = 1.0 - _KR - _KB
_RGB_A_YUV = np.array([
    [_KR, _KG, _KB],
    [-_KR / (2 * (1 - _KB)), -_KG / (2 * (1 - _KB)), 0.5],
    [0.5, -_KG / (2 * (1 - _KR)), -_KB / (2 * (1 - _KR))],
], dtype=np.float32)
_YUV_A_RGB = np.linalg.inv(_RGB_A_YUV).astype(np.float32)
_PESI_LUMA = _RGB_A_YUV[0]


class ColorSmoother:
    """Transizioni tra un frame e il successivo. Due modalità
    (config.SMOOTHING_MODE), entrambe con costante di tempo reale (non
    per-frame: il loop di cattura gira a ritmo variabile, e una alpha fissa
    per frame renderebbe la transizione più lenta o più rapida in tempo reale
    a seconda di quanti frame arrivano al secondo).

    "esponenziale" (default) — attacco/decadimento ASIMMETRICO:
    - Quando un canale diventa più intenso ("attacco"): reazione quasi
      istantanea (ATTACK_S). Cattura i lampi anche di un solo frame, e nel
      caso di un vero cambio scena più luminoso evita una transizione
      superflua — in entrambi i casi vuoi vederlo subito.
    - Quando un canale si attenua ("decadimento"): segue la curva morbida
      impostata con lo slider Smoothing (MAX_SMOOTHING_S alla quantità
      massima). È dove ha senso la morbidezza: lo spegnersi di un lampo, o
      un fade naturale della scena.
    Non è possibile distinguere con certezza "lampo che sta per sparire" da
    "cambio vero e duraturo" nell'istante in cui succede, senza introdurre
    un ritardo artificiale — questa euristica (aumento=veloce sempre,
    diminuzione=morbida) è il compromesso usato in VU-meter, esposimetri e
    altri sistemi ambilight reali, e risolve il caso comune di entrambi gli
    obiettivi senza aggiungere latenza.

    "molla" — ogni LED è una molla smorzata in spazio YUV, SIMMETRICA (sale e scende alla stessa
    velocità). La luminanza e il colore si muovono in modo indipendente, e
    l'inerzia fa partire e arrivare il movimento in modo dolce invece che con
    una curva esponenziale che parte a velocità massima. Qui è a smorzamento
    critico (nessun overshoot) con soluzione esatta per intervallo, quindi
    stabile a qualunque dt. Lo slider Smoothing regola la velocità come
    nell'altra modalità.

    In entrambe, config.Y_LIMIT (se > 0) limita quanto può cambiare la
    LUMINANZA di un LED al secondo (frazione del fondo scala): attenua i
    lampi improvvisi. Lo snap sui tagli di scena
    (SNAP_THRESHOLD) lo scavalca di proposito."""

    MAX_SMOOTHING_S = 0.35    # costante di tempo del decadimento alla quantità massima di smoothing
    ATTACK_S        = 0.005   # costante di tempo dell'attacco — ~86% di convergenza in un frame a 100fps

    # Soglie con cui la molla si considera arrivata
    _EPS_POS = 1.0e-4
    _EPS_VEL = 1.0e-3

    def __init__(self, n):
        self._cur    = np.zeros((n, 3), dtype=np.float32)
        self._yuv    = np.zeros((n, 3), dtype=np.float32)   # stato della molla (0..1)
        self._vel    = np.zeros((n, 3), dtype=np.float32)
        self._yuv_ok = False   # lo stato YUV è allineato a _cur?
        self._last_t = time.perf_counter()

    # ---- passi di integrazione ------------------------------------------
    def _passo_esponenziale(self, t, dt, f):
        # alpha per canale: attacco (t > cur) quasi istantaneo, decadimento
        # (t < cur) con la costante di tempo del decadimento configurata.
        alpha_decadimento = 1.0 - np.exp(-dt / (f * self.MAX_SMOOTHING_S))
        alpha_attacco     = 1.0 - np.exp(-dt / self.ATTACK_S)
        alpha = np.where(t > self._cur, alpha_attacco, alpha_decadimento)
        nuovo = self._cur + (t - self._cur) * alpha
        self._yuv_ok = False
        return nuovo.astype(np.float32), None

    def _passo_molla(self, t, dt, f):
        if not self._yuv_ok:
            self._yuv = (self._cur / 255.0) @ _RGB_A_YUV.T
            self._vel[:] = 0
            self._yuv_ok = True

        tgt = (t / 255.0) @ _RGB_A_YUV.T
        w   = 2.0 / (f * self.MAX_SMOOTHING_S)      # smorzamento critico: c = 2w, k = w^2
        x0  = self._yuv - tgt
        v0  = self._vel
        e   = np.exp(-w * dt)
        a   = v0 + w * x0
        x   = (x0 + a * dt) * e
        v   = (v0 - w * a * dt) * e

        # arrivata: posizione e velocità trascurabili -> aggancio esatto
        fermo = ((np.abs(x) < self._EPS_POS).all(axis=1)
                 & (np.abs(v) < self._EPS_VEL).all(axis=1))[:, None]
        x = np.where(fermo, 0.0, x)
        v = np.where(fermo, 0.0, v)
        return (tgt + x).astype(np.float32), v.astype(np.float32)

    def _limita_luminanza(self, prec, nuovo, dt, limite_s):
        """Scala il passo (prec -> nuovo) in modo che la luminanza non cambi
        più di limite_s*dt. Ritorna il fattore per LED (1 = nessun taglio)."""
        massimo = limite_s * dt
        dy = np.abs((nuovo - prec) @ _PESI_LUMA)
        return np.where(dy > massimo, massimo / np.maximum(dy, 1e-9), 1.0).astype(np.float32)

    # ---- API -------------------------------------------------------------
    def aggiorna(self, target: np.ndarray) -> np.ndarray:
        now = time.perf_counter()
        dt  = max(1e-4, now - self._last_t)
        self._last_t = now

        f = config.SMOOTHING_FACTOR   # 0 = istantaneo, vicino a 1 = molto smooth (vedi config.py)
        t = target.astype(np.float32)

        # Smoothing disabilitato → aggiornamento istantaneo
        if f <= 0.0:
            self._cur = t
            self._yuv_ok = False
            return self._cur

        thr  = getattr(config, "SNAP_THRESHOLD", 80)
        ylim = float(getattr(config, "Y_LIMIT", 0.0))

        if getattr(config, "SMOOTHING_MODE", "esponenziale") == "molla":
            yuv, vel = self._passo_molla(t, dt, f)
            nuovo = np.clip(yuv @ _YUV_A_RGB.T * 255.0, 0.0, 255.0)
            if ylim > 0:
                k = self._limita_luminanza(self._cur, nuovo, dt, ylim * 255.0)[:, None]
                nuovo = self._cur + (nuovo - self._cur) * k
                yuv   = self._yuv + (yuv - self._yuv) * k
                vel   = vel * k
            self._yuv, self._vel = yuv, vel
        else:
            nuovo, _ = self._passo_esponenziale(t, dt, f)
            if ylim > 0:
                k = self._limita_luminanza(self._cur, nuovo, dt, ylim * 255.0)[:, None]
                nuovo = self._cur + (nuovo - self._cur) * k

        if thr > 0:
            # LED con cambio brusco (taglio di scena): snap immediato
            snap = np.abs(t - self._cur).max(axis=1) > thr   # shape (N,)
            if snap.any():
                nuovo[snap] = t[snap]
                if self._yuv_ok:
                    self._yuv[snap] = (t[snap] / 255.0) @ _RGB_A_YUV.T
                    self._vel[snap] = 0

        self._cur = nuovo.astype(np.float32)
        return self._cur

    def reset(self):
        self._cur[:] = 0
        self._yuv[:] = 0
        self._vel[:] = 0
        self._yuv_ok = False
        self._last_t = time.perf_counter()


# =============================================================================
# BlackBarDetector — rilevamento dinamico letterbox/pillarbox
# =============================================================================

class BlackBarDetector:
    """Rileva barre nere ai bordi del frame (letterbox/pillarbox) e restituisce
    di quanti pixel (thumbnail space) restringere il sampling su ogni lato.

    Isteresi temporale ASIMMETRICA: serve ~1s di conferma continua per far
    CRESCERE una barra rilevata, ma bastano ~0.3s senza barra per farla
    sparire. Così una dissolvenza al nero (scena scura, non letterbox) non fa
    scattare la detection, ma un vero cambio di inquadratura la rimuove in
    fretta. Il chiamante passa anche un rapporto massimo (BLACKBAR_MAX_RATIO):
    oltre quella soglia un frame tutto nero viene trattato come scena scura
    (i LED si spengono via SOGLIA_MINIMA come già accade) invece che come
    "barra infinita" che divora tutta la zona di campionamento.
    """

    TAU_CRESCITA  = 1.0   # secondi per assestarsi su una barra più grande
    TAU_RIMOZIONE = 0.3   # secondi per farla sparire

    # Una riga/colonna conta come "contenuto" solo se almeno questa frazione
    # dei suoi pixel supera la soglia. Con il vecchio massimo (1 solo pixel)
    # un logo, un OSD o un pixel caldo bastavano a far sparire la barra.
    FRAZIONE_MIN = 0.03
    # Sul bordo in basso si ignora la fascia centrale, dove cadono i
    # sottotitoli dentro la barra nera: il centro si controlla solo in alto.
    FASCIA_LATERALE = 0.25
    # Frazione minima di pixel luminosi nell'intero frame perché la detection
    # sia attendibile; sotto, è una pagina/scena nera e le barre si ritirano.
    FRAZIONE_FRAME_MIN = 0.02
    # Margine aggiunto a una barra rilevata (anti-blur).
    MARGINE_PX = 1

    def __init__(self):
        self.top = self.bottom = self.left = self.right = 0.0
        self._last_t = time.perf_counter()

    @classmethod
    def _primo_contenuto(cls, frazioni: np.ndarray, cap: int) -> int:
        """Indice (dal bordo verso il centro) della prima riga/colonna con
        abbastanza pixel luminosi, più il margine anti-blur; 0 (nessuna barra)
        se nessuna lo è entro la finestra cercata: è una scena scura, non
        una barra più larga del massimo consentito."""
        trovate = np.flatnonzero(frazioni >= cls.FRAZIONE_MIN)
        if not trovate.size:
            return 0
        i = int(trovate[0])
        return min(i + cls.MARGINE_PX, cap) if i > 0 else 0

    def _insegui(self, attuale: float, candidato: int, dt: float) -> float:
        tau   = self.TAU_CRESCITA if candidato > attuale else self.TAU_RIMOZIONE
        alpha = min(1.0, dt / tau)
        return attuale + (candidato - attuale) * alpha

    def aggiorna(self, frame_gray: np.ndarray, soglia: float, max_ratio: float):
        now = time.perf_counter()
        dt  = max(1e-4, now - self._last_t)
        self._last_t = now

        h, w  = frame_gray.shape
        max_h = max(1, int(h * max_ratio))
        max_w = max(1, int(w * max_ratio))
        lato  = max(1, int(w * self.FASCIA_LATERALE))

        luminoso = frame_gray >= soglia

        # Pagina/scena quasi tutta nera: nessun contenuto da cui dedurre una
        # barra, quindi nessuna barra (le barre si ritirano con TAU_RIMOZIONE).
        if luminoso.mean() < self.FRAZIONE_FRAME_MIN:
            self.top    = self._insegui(self.top,    0, dt)
            self.bottom = self._insegui(self.bottom, 0, dt)
            self.left   = self._insegui(self.left,   0, dt)
            self.right  = self._insegui(self.right,  0, dt)
            return

        fr_top   = luminoso[:max_h].mean(axis=1)
        fr_bottom = np.concatenate([luminoso[h - max_h:, :lato],
                                    luminoso[h - max_h:, w - lato:]],
                                   axis=1).mean(axis=1)[::-1]
        fr_left   = luminoso[:, :max_w].mean(axis=0)
        fr_right  = luminoso[:, w - max_w:].mean(axis=0)[::-1]

        self.top    = self._insegui(self.top,    self._primo_contenuto(fr_top,    max_h), dt)
        self.bottom = self._insegui(self.bottom, self._primo_contenuto(fr_bottom, max_h), dt)
        self.left   = self._insegui(self.left,   self._primo_contenuto(fr_left,   max_w), dt)
        self.right  = self._insegui(self.right,  self._primo_contenuto(fr_right,  max_w), dt)

    def reset(self):
        self.top = self.bottom = self.left = self.right = 0.0


# =============================================================================
# ScreenProcessor
# =============================================================================

class ScreenProcessor:
    def __init__(self, seriale=None):
        self._seriale  = seriale
        self._smoother = ColorSmoother(LED_TOTAL)
        self._barre    = BlackBarDetector()
        self._dither   = TemporalDither(LED_TOTAL)
        self._dither_cal = TemporalDither(LED_TOTAL)   # pattern di calibrazione
        # False = il thread di cattura non scrive sulla seriale (modalità test
        # LED: i colori di test li invia il controller e non devono alternarsi
        # con quelli dello schermo).
        self.invio_attivo = True
        self._lock     = threading.Lock()
        self._ultimi   = np.zeros((LED_TOTAL, 3), dtype=np.uint8)
        self._stop     = threading.Event()
        self._fps      = 0.0

        # ---- Stats thread-safe ----------------------------------------
        self._stats = {
            "fps_capture": 0.0,
            "ms_capture":  0.0,   # tempo medio cattura frame
            "ms_calcola":  0.0,   # tempo medio calcolo colori
            "ms_serial":   0.0,   # tempo medio invio seriale
            "latency_ms":  0.0,   # latenza totale pipeline (cattura + calcolo)
        }
        self._stats_lock = threading.Lock()
        # ----------------------------------------------------------------

        with mss.mss() as sct:
            # monitors[0] è il desktop virtuale: i singoli monitor partono da 1
            idx = min(max(config.MONITOR_INDEX, 0), len(sct.monitors) - 2) + 1
            m = sct.monitors[idx]
            self.screen_w, self.screen_h = m["width"], m["height"]

        self.refresh_hz = _rileva_refresh_rate()
        if self.refresh_hz:
            print(f"[Main] Refresh rate rilevato: {self.refresh_hz}Hz")

        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    # Alias pubblico comodo
    @property
    def smoother(self) -> ColorSmoother:
        return self._smoother

    @property
    def barre(self) -> BlackBarDetector:
        return self._barre

    def set_seriale(self, s):
        self._seriale = s

    # ------------------------------------------------------------------
    def _loop(self):
        try:
            import ctypes; ctypes.windll.winmm.timeBeginPeriod(1)
        except Exception:
            pass

        # target_fps=0 disabilita il pacing a timer di dxcam (corsa scoperta,
        # limitata solo da quando la Desktop Duplication API rende disponibile
        # un nuovo frame). Un pacing esplicito dà un ritmo stabile invece che
        # scoperto — ma misurato: la CPU usata è quasi proporzionale al target
        # (144fps ≈235% CPU, 60fps ≈153%, 30fps ≈65%), quindi si usa il minimo
        # tra il refresh nativo del monitor e CAPTURE_FPS_CAP, mai il refresh
        # nativo intero se questo è più alto del necessario per un ambilight.
        target_fps_cam = min(self.refresh_hz, config.CAPTURE_FPS_CAP) if self.refresh_hz else config.CAPTURE_FPS_CAP

        def crea_cam():
            # BGRA invece di RGB: è il formato nativo con cui Desktop Duplication
            # consegna i pixel — chiedere RGB costringe dxcam a riordinare i canali
            # e scartare l'alpha sul frame INTERO (2560x1440) ad ogni cattura,
            # misurato ~2.6x più costoso. Convertiamo noi stessi in RGB dentro
            # _calcola(), ma DOPO il downsample: sulla miniatura 256x144 il
            # riordino costa quasi zero (100x meno pixel da toccare).
            c = dxcam.create(device_idx=0, output_idx=config.MONITOR_INDEX,
                            output_color="BGRA", max_buffer_len=2)
            c.start(target_fps=target_fps_cam, video_mode=True)
            return c

        if _DXCAM_AVAILABLE:
            cam = crea_cam()
            get_frame = cam.get_latest_frame
            self._cam = cam
            print(f"[Capture] dxcam GPU — buffer=2, target_fps={target_fps_cam or 'scoperto'}")
        else:
            sct = mss.mss()
            mon = sct.monitors[min(max(config.MONITOR_INDEX, 0), len(sct.monitors) - 2) + 1]
            print("[Capture] mss CPU")
            def get_frame():
                return np.array(sct.grab(mon))[:,:,:3][:,:,::-1]
            self._cam = None

        t0, frames = time.perf_counter(), 0
        t_capture = t_calcola = t_serial = 0.0
        profile_n = 0
        none_da   = None          # timestamp del primo None consecutivo

        while not self._stop.is_set():
            _t = time.perf_counter()
            try:
                frame = get_frame()
            except Exception:
                frame = None
            t_capture += time.perf_counter() - _t

            if frame is None:
                # dxcam: se restiamo a secco troppo a lungo la camera è morta → ricrea
                if _DXCAM_AVAILABLE:
                    now = time.perf_counter()
                    if none_da is None:
                        none_da = now
                    elif now - none_da > 0.5:
                        print("[Capture] dxcam access lost — ricreo la camera")
                        try: cam.stop()
                        except Exception: pass
                        try: cam.release()
                        except Exception: pass
                        time.sleep(0.3)
                        try:
                            cam = crea_cam()
                            get_frame = cam.get_latest_frame
                            self._cam = cam
                        except Exception as e:
                            print(f"[Capture] ricreazione fallita: {e}")
                            time.sleep(1.0)
                        none_da = None
                time.sleep(0.002)
                continue

            none_da = None

            _t = time.perf_counter()
            raw    = self._calcola(frame)
            smooth = self._smoother.aggiorna(raw)
            result = self._dither.applica(smooth)
            t_calcola += time.perf_counter() - _t

            with self._lock:
                self._ultimi = result

            _t = time.perf_counter()
            if self.invio_attivo and self._seriale and self._seriale.buffer_libero():
                self._seriale.invia_colori(result)
            t_serial += time.perf_counter() - _t

            frames    += 1
            profile_n += 1
            elapsed    = time.perf_counter() - t0

            if elapsed >= 2.0:
                self._fps = frames / elapsed
                if profile_n > 0:
                    ms_cap = t_capture / profile_n * 1000
                    ms_cal = t_calcola / profile_n * 1000
                    ms_ser = t_serial  / profile_n * 1000
                    with self._stats_lock:
                        self._stats.update({
                            "fps_capture": self._fps,
                            "ms_capture":  ms_cap,
                            "ms_calcola":  ms_cal,
                            "ms_serial":   ms_ser,
                            "latency_ms":  ms_cap + ms_cal,
                        })
                frames    = 0
                t_capture = t_calcola = t_serial = 0.0
                profile_n = 0
                t0        = time.perf_counter()

        if _DXCAM_AVAILABLE and getattr(self, "_cam", None):
            try: self._cam.stop()
            except Exception: pass
        try:
            import ctypes; ctypes.windll.winmm.timeEndPeriod(1)
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _area_contenuto(self, sw: int, sh: int) -> tuple:
        """Contenuto (x0, x1, y0, y1) in pixel miniatura, senza le barre nere
        attualmente rilevate. Se le barre lo schiacciano troppo, tutto lo schermo."""
        area = (int(self._barre.left), sw - int(self._barre.right),
                int(self._barre.top), sh - int(self._barre.bottom))
        if area[1] - area[0] < 8 or area[3] - area[2] < 8:
            return (0, sw, 0, sh)
        return area

    def geometria_aree(self) -> dict | None:
        """Aree di campionamento attuali in pixel miniatura, per l'anteprima
        della UI. None finché non è arrivato il primo frame."""
        aspetto = getattr(self, "_aspetto", None)
        if aspetto is None:
            return None
        area = self._area_contenuto(THUMB_W, THUMB_H)
        return {"area": area, "rects": _rettangoli_aree_pixel(area, aspetto),
                "thumb": (THUMB_W, THUMB_H)}

    def _calcola(self, frame: np.ndarray) -> np.ndarray:
        self._aspetto = frame.shape[0] / frame.shape[1]
        frame = _riduci_a_miniatura(frame)

        # dxcam consegna BGRA (formato nativo, zero conversione a monte — vedi
        # crea_cam()). Il riordino canali avviene QUI, sulla miniatura già
        # ridotta, non sul frame intero: ~100x meno pixel da toccare rispetto
        # a farlo fare a dxcam sul frame a piena risoluzione. mss (fallback
        # CPU) consegna già RGB a 3 canali, quindi non serve alcun riordino.
        if frame.shape[2] == 4:
            frame = frame[:, :, [2, 1, 0]]  # BGRA -> RGB, scarta l'alpha

        sh, sw = frame.shape[:2]
        ox = int(sw * config.SAMPLE_OFFSET_RATIO)
        oy = int(sh * config.SAMPLE_OFFSET_RATIO)
        dx = max(int(sw * config.SAMPLE_DEPTH_RATIO), config.SAMPLE_DEPTH_MIN)
        dy = max(int(sh * config.SAMPLE_DEPTH_RATIO), config.SAMPLE_DEPTH_MIN)

        # Valori codificati in float: servono per la luminanza (maschere) e,
        # se LINEAR_AVERAGING è spento, anche per la media.
        enc  = frame.astype(np.float32)
        luma = 0.299 * enc[:, :, 0] + 0.587 * enc[:, :, 1] + 0.114 * enc[:, :, 2]
        lineare = bool(config.LINEAR_AVERAGING)
        src = _SRGB_TO_LIN[frame] if lineare else enc

        # ---- Barre nere (letterbox/pillarbox): restringe il sampling verso
        # il centro del contenuto reale, in aggiunta all'offset già configurato ----
        if config.BLACKBAR_DETECTION:
            self._barre.aggiorna(luma, config.BLACKBAR_SOGLIA, config.BLACKBAR_MAX_RATIO)
            bar_top, bar_bottom = self._barre.top, self._barre.bottom
            bar_left, bar_right = self._barre.left, self._barre.right
        else:
            self._barre.reset()
            bar_top = bar_bottom = bar_left = bar_right = 0.0

        if config.SAMPLING_MODE == "aree":
            segs = _campiona_aree(src, self._area_contenuto(sw, sh), self._aspetto)
        else:
            oy_top    = min(oy + int(bar_top),    sh // 2 - 1)
            oy_bottom = min(oy + int(bar_bottom), sh // 2 - 1)
            ox_left   = min(ox + int(bar_left),   sw // 2 - 1)
            ox_right  = min(ox + int(bar_right),  sw // 2 - 1)

            soglia = config.SOGLIA_MINIMA

            def zona(y0, y1, x0, x1, n, verticale, inverti):
                """Colore medio di `n` LED allineati lungo la zona. I LED sono
                sempre disposti lungo l'asse 1 dopo l'eventuale scambio degli
                assi, così sopra/sotto e lati condividono lo stesso calcolo."""
                l = luma[y0:y1, x0:x1]
                c = src[y0:y1, x0:x1]
                if verticale:
                    l, c = l.swapaxes(0, 1), c.swapaxes(0, 1)
                H, W = l.shape
                if W < n or H == 0:        # zona degenere (barre enormi): LED spenti
                    return np.zeros((n, 3), dtype=np.float32)
                wc = (W // n) * n
                l = l[:, :wc].reshape(H, n, wc // n)
                c = c[:, :wc].reshape(H, n, wc // n, 3)

                # soglia (75° percentile della luminanza) PER OGNI LED: i gruppi
                # sono i segmenti (asse 1), non bande di righe — il vecchio
                # reshape(n, -1) sulle zone orizzontali mescolava pixel di LED
                # diversi e poteva spegnere un LED scuro con la soglia di uno chiaro.
                lf  = l.transpose(1, 0, 2).reshape(n, -1)
                k   = max(1, int(lf.shape[1] * 0.75))
                thr = np.maximum(np.partition(lf, k, axis=1)[:, k], soglia)
                mask = (l >= thr[None, :, None]).astype(np.float32)
                cnt  = mask.sum(axis=(0, 2)) + 1e-6
                out  = np.einsum('hnw,hnwc->nc', mask, c) / cnt[:, None]
                return out[::-1].copy() if inverti else out

            # I lati verticali si accorciano con le barre sopra/sotto, quelli
            # orizzontali con le barre a sinistra/destra: altrimenti i LED laterali
            # restano distribuiti sull'altezza intera, barre incluse.
            segs = np.vstack([
                zona(oy_top, sh - oy_bottom, sw - ox_right - dx, sw - ox_right, LED_RIGHT,  True,  True),
                zona(oy_top, oy_top + dy,    ox_left, sw - ox_right,            LED_TOP,    False, True),
                zona(oy_top, sh - oy_bottom, ox_left, ox_left + dx,             LED_LEFT,   True,  False),
                zona(sh - oy_bottom - dy, sh - oy_bottom, ox_left, sw - ox_right, LED_BOTTOM, False, False),
            ])

        if lineare:
            segs = _lineare_a_srgb255(segs)

        return self._post(segs)

    def _post(self, segs: np.ndarray) -> np.ndarray:
        """Elaborazione finale comune a schermo e pattern di calibrazione:
        soglia, saturazione, matrice colore + guadagni di calibrazione, gamma,
        limite di potenza. `segs`: (LED_TOTAL, 3) in sRGB 0-255. Ritorna
        valori di uscita float 0-255, prima del dithering."""
        spenti = (segs < config.SOGLIA_MINIMA).all(axis=1)
        segs[spenti] = 0

        boost = config.SATURATION_BOOST
        if boost != 1.0:
            segs = _sat_boost_batch(segs, boost)

        matrice = np.array(config.COLOR_MATRIX, dtype=np.float32)
        guadagni = config.WHITE_GAINS
        if guadagni != [1.0, 1.0, 1.0]:
            matrice = np.diag(np.array(guadagni, dtype=np.float32)) @ matrice
        if not np.array_equal(matrice, np.eye(3, dtype=np.float32)):
            segs = _applica_color_matrix(segs, matrice)

        # Gamma in float (nessuna LUT a 8 bit): la quantizzazione a 8 bit
        # avviene solo alla fine, con il dithering (vedi TemporalDither).
        segs = np.clip(segs, 0, 255).astype(np.float32)
        out  = 255.0 * np.power(segs / 255.0, np.float32(config.GAMMA))

        # Limite di potenza: i valori post-gamma sono proporzionali al PWM,
        # quindi alla corrente assorbita.
        limite = config.POWER_LIMIT
        if limite < 1.0:
            budget = out.size * 255.0 * max(limite, 0.0)
            totale = float(out.sum())
            if totale > budget:
                out *= budget / totale
        return out.astype(np.float32)

    def colori_pattern(self, livello: int) -> np.ndarray:
        """Grigio uniforme (livello sRGB 0-255) su tutti i LED, passato dalla
        STESSA elaborazione finale dello schermo: serve a calibrare il bianco
        vedendo l'effetto reale di matrice, guadagni e gamma."""
        segs = np.full((LED_TOTAL, 3), float(livello), dtype=np.float32)
        return self._dither_cal.applica(self._post(segs), sempre=True)

    # ------------------------------------------------------------------
    # API pubblica
    # ------------------------------------------------------------------

    def calcola_colori(self):
        with self._lock:
            return [(int(r), int(g), int(b)) for r, g, b in self._ultimi]

    def get_stats(self) -> dict:
        """Restituisce una copia thread-safe delle statistiche di cattura."""
        with self._stats_lock:
            return dict(self._stats)

    def get_info_monitor(self):
        return {"larghezza": self.screen_w, "altezza": self.screen_h,
                "profondita_x": 0, "profondita_y": 0,
                "refresh_hz": self.refresh_hz}

    def get_capture_fps(self):
        return self._fps

    def stop(self):
        self._stop.set()
        if getattr(self, "_cam", None):
            try:
                self._cam.stop()
            except Exception:
                pass