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


def _build_gamma_table(gamma: float) -> np.ndarray:
    t = np.zeros(256, dtype=np.uint8)
    for i in range(256):
        t[i] = int((i / 255.0) ** gamma * 255.0 + 0.5)
    return t


def _sat_boost_batch(rgb: np.ndarray, boost: float) -> np.ndarray:
    """Boost saturazione completamente vettorizzato — zero loop Python."""
    if boost == 1.0:
        return rgb
    f = rgb / 255.0
    r, g, b = f[:,0], f[:,1], f[:,2]
    cmax  = f.max(axis=1)
    cmin  = f.min(axis=1)
    delta = cmax - cmin

    s = np.where(cmax > 1e-6, delta / cmax, 0.0)
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

class ColorSmoother:
    """Interpolazione con costante di tempo reale (non per-frame) e attacco/
    decadimento ASIMMETRICO:

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
    altri sistemi ambient light reali, e risolve il caso comune di entrambi gli
    obiettivi senza aggiungere latenza.

    Costante di tempo reale, non per-frame: il loop di cattura gira scoperto
    (nessun limite di fps fisso), e una alpha fissa per-frame renderebbe la
    transizione più lenta o più rapida IN TEMPO REALE a seconda di quanto
    velocemente arrivano i frame. Qui la costante di tempo è fissa in
    secondi, il framerate può variare quanto vuole senza cambiare la durata
    percepita."""

    MAX_SMOOTHING_S = 0.35    # costante di tempo del decadimento alla quantità massima di smoothing
    ATTACK_S        = 0.005   # costante di tempo dell'attacco — ~86% di convergenza in un frame a 100fps

    def __init__(self, n):
        self._cur    = np.zeros((n, 3), dtype=np.float32)
        self._last_t = time.perf_counter()

    def aggiorna(self, target: np.ndarray) -> np.ndarray:
        now = time.perf_counter()
        dt  = max(1e-4, now - self._last_t)
        self._last_t = now

        f = config.SMOOTHING_FACTOR   # 0 = istantaneo, vicino a 1 = molto smooth (vedi config.py)
        t = target.astype(np.float32)

        # Smoothing disabilitato → aggiornamento istantaneo
        if f <= 0.0:
            self._cur = t
            return self._cur

        thr = getattr(config, "SNAP_THRESHOLD", 80)

        # alpha per canale: attacco (t > cur) quasi istantaneo, decadimento
        # (t < cur) con la costante di tempo del decadimento configurata.
        alpha_decadimento = 1.0 - np.exp(-dt / (f * self.MAX_SMOOTHING_S))
        alpha_attacco      = 1.0 - np.exp(-dt / self.ATTACK_S)
        alpha = np.where(t > self._cur, alpha_attacco, alpha_decadimento)

        if thr > 0:
            # Calcola il delta massimo per canale su ogni LED
            delta = np.abs(t - self._cur).max(axis=1)   # shape (N,)
            snap  = delta > thr                          # mask LED che "saltano"

            # LED con cambio brusco (taglio di scena): snap immediato
            self._cur[snap]  = t[snap]
            # LED con cambio graduale: interpolazione morbida (asimmetrica)
            self._cur[~snap] += (t[~snap] - self._cur[~snap]) * alpha[~snap]
        else:
            # Snap disabilitato: interpolazione pura per tutti i LED
            self._cur += (t - self._cur) * alpha

        return self._cur

    def reset(self):
        self._cur[:] = 0
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

    def __init__(self):
        self.top = self.bottom = self.left = self.right = 0.0
        self._last_t = time.perf_counter()

    @staticmethod
    def _primo_luminoso(profilo: np.ndarray, soglia: float, cap: int) -> int:
        """Indice (dal bordo verso il centro) del primo campione >= soglia,
        o `cap` se nessun campione supera la soglia entro la finestra cercata."""
        bright = np.flatnonzero(profilo >= soglia)
        return int(bright[0]) if bright.size else cap

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

        row_max = frame_gray.max(axis=1)
        col_max = frame_gray.max(axis=0)

        cand_top    = self._primo_luminoso(row_max[:max_h],        soglia, max_h)
        cand_bottom = self._primo_luminoso(row_max[::-1][:max_h],  soglia, max_h)
        cand_left   = self._primo_luminoso(col_max[:max_w],        soglia, max_w)
        cand_right  = self._primo_luminoso(col_max[::-1][:max_w],  soglia, max_w)

        self.top    = self._insegui(self.top,    cand_top,    dt)
        self.bottom = self._insegui(self.bottom, cand_bottom, dt)
        self.left   = self._insegui(self.left,   cand_left,   dt)
        self.right  = self._insegui(self.right,  cand_right,  dt)

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
        self._gamma    = _build_gamma_table(config.GAMMA)
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

        if _DXCAM_AVAILABLE:
            import ctypes
            self.screen_w = ctypes.windll.user32.GetSystemMetrics(0)
            self.screen_h = ctypes.windll.user32.GetSystemMetrics(1)
        else:
            with mss.mss() as sct:
                m = sct.monitors[1]
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
        # nativo intero se questo è più alto del necessario per un ambient light.
        target_fps_cam = min(self.refresh_hz, config.CAPTURE_FPS_CAP) if self.refresh_hz else config.CAPTURE_FPS_CAP

        def crea_cam():
            # BGRA invece di RGB: è il formato nativo con cui Desktop Duplication
            # consegna i pixel — chiedere RGB costringe dxcam a riordinare i canali
            # e scartare l'alpha sul frame INTERO (2560x1440) ad ogni cattura,
            # misurato ~2.6x più costoso. Convertiamo noi stessi in RGB dentro
            # _calcola(), ma DOPO il downsample: sulla miniatura 256x144 il
            # riordino costa quasi zero (100x meno pixel da toccare).
            c = dxcam.create(device_idx=0, output_idx=0,   # ← metti l'idx giusto
                            output_color="BGRA", max_buffer_len=2)
            c.start(target_fps=target_fps_cam, video_mode=True)
            return c

        if _DXCAM_AVAILABLE:
            cam = crea_cam()
            get_frame = cam.get_latest_frame
            self._cam = cam
            print(f"[Capture] dxcam GPU — buffer=2, target_fps={target_fps_cam or 'scoperto'}")
        else:
            sct = mss.mss(); mon = sct.monitors[1]
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
            result = np.clip(smooth, 0, 255).astype(np.uint8)
            t_calcola += time.perf_counter() - _t

            with self._lock:
                self._ultimi = result

            _t = time.perf_counter()
            if self._seriale and self._seriale.buffer_libero():
                self._seriale.invia_colori(
                    [(int(r), int(g), int(b)) for r, g, b in result])
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

    # ------------------------------------------------------------------
    def _calcola(self, frame: np.ndarray) -> np.ndarray:
        THUMB_W, THUMB_H = 256, 144
        fh, fw = frame.shape[:2]
        sy = max(1, fh // THUMB_H)
        sx = max(1, fw // THUMB_W)
        frame = frame[::sy, ::sx, :][:THUMB_H, :THUMB_W, :]

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

        # ---- Barre nere (letterbox/pillarbox): restringe il sampling verso
        # il centro del contenuto reale, in aggiunta all'offset già configurato ----
        if config.BLACKBAR_DETECTION:
            gray = (0.299 * frame[:, :, 0] + 0.587 * frame[:, :, 1]
                    + 0.114 * frame[:, :, 2]).astype(np.float32)
            self._barre.aggiorna(gray, config.SOGLIA_MINIMA, config.BLACKBAR_MAX_RATIO)
            bar_top, bar_bottom = self._barre.top, self._barre.bottom
            bar_left, bar_right = self._barre.left, self._barre.right
        else:
            self._barre.reset()
            bar_top = bar_bottom = bar_left = bar_right = 0.0

        oy_top    = min(oy + int(bar_top),    sh // 2 - 1)
        oy_bottom = min(oy + int(bar_bottom), sh // 2 - 1)
        ox_left   = min(ox + int(bar_left),   sw // 2 - 1)
        ox_right  = min(ox + int(bar_right),  sw // 2 - 1)

        def seg_h(y0, y1, n, inv):
            s  = frame[y0:y1, ox:sw-ox].astype(np.float32)
            H, W = s.shape[:2]
            wc = (W // n) * n
            s  = s[:, :wc, :].reshape(H, n, wc//n, 3)
            luma = 0.299*s[:,:,:,0] + 0.587*s[:,:,:,1] + 0.114*s[:,:,:,2]
            lf   = luma.reshape(n, -1)
            k    = max(1, int(lf.shape[1] * 0.75))
            thr  = np.maximum(np.partition(lf, k, axis=1)[:,k], config.SOGLIA_MINIMA)
            mask = (luma >= thr[:,None]).astype(np.float32)
            cnt  = mask.sum(axis=(0,2)) + 1e-6
            r = (s[:,:,:,0]*mask).sum(axis=(0,2))/cnt
            g = (s[:,:,:,1]*mask).sum(axis=(0,2))/cnt
            b = (s[:,:,:,2]*mask).sum(axis=(0,2))/cnt
            out = np.stack([r,g,b],axis=1)
            return out[::-1].copy() if inv else out

        def seg_v(x0, x1, n, inv):
            s  = frame[oy:sh-oy, x0:x1].astype(np.float32)
            H, W = s.shape[:2]
            hc = (H // n) * n
            s  = s[:hc, :, :].reshape(n, hc//n, W, 3)
            luma = 0.299*s[:,:,:,0] + 0.587*s[:,:,:,1] + 0.114*s[:,:,:,2]
            lf   = luma.reshape(n, -1)
            k    = max(1, int(lf.shape[1] * 0.75))
            thr  = np.maximum(np.partition(lf, k, axis=1)[:,k], config.SOGLIA_MINIMA)
            mask = (luma >= thr[:,None,None]).astype(np.float32)
            cnt  = mask.sum(axis=(1,2)) + 1e-6
            r = (s[:,:,:,0]*mask).sum(axis=(1,2))/cnt
            g = (s[:,:,:,1]*mask).sum(axis=(1,2))/cnt
            b = (s[:,:,:,2]*mask).sum(axis=(1,2))/cnt
            out = np.stack([r,g,b],axis=1)
            return out[::-1].copy() if inv else out

        segs = np.vstack([
            seg_v(sw-ox_right-dx,  sw-ox_right,  LED_RIGHT,  True),
            seg_h(oy_top,          oy_top+dy,    LED_TOP,    True),
            seg_v(ox_left,         ox_left+dx,   LED_LEFT,   False),
            seg_h(sh-oy_bottom-dy, sh-oy_bottom, LED_BOTTOM, False),
        ])

        spenti = (segs < config.SOGLIA_MINIMA).all(axis=1)
        segs[spenti] = 0

        boost = config.SATURATION_BOOST
        if boost != 1.0:
            segs = _sat_boost_batch(segs, boost)

        matrice = config.COLOR_MATRIX
        if matrice != IDENTITA_COLOR_MATRIX:
            segs = _applica_color_matrix(segs, np.array(matrice, dtype=np.float32))

        idx = np.clip(segs, 0, 255).astype(np.uint8)
        return self._gamma[idx].astype(np.float32)

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