# ESP32 Ambient Light

Bias lighting for a PC monitor: an **ESP32** drives a **WS2812B LED strip** placed behind the screen, and a Python application captures the screen, computes the colours along its edges and streams them to the strip in real time.

Personal hardware + software project. Inspired by *OziLight* by Oscar Liang, rewritten as a modular Python application. Code comments and the interface are in Italian.

## How it works

1. **Capture**: the screen is grabbed with `mss` and sampled in zones along the four edges, one zone per LED. The sampling depth adapts to the monitor resolution.
2. **Colour processing**: averaging per zone, smoothing with a snap threshold (so scene cuts are still instant), gamma correction, saturation boost, a 3×3 colour-correction matrix to balance the strip's white point, and dynamic **black-bar detection** for letterboxed video.
3. **Transport**: frames go over USB serial (460800 baud) with a small custom protocol: magic bytes, LED count, RGB values and a CRC8 checksum. The firmware checks the checksum, and turns the strip off if no valid packet arrives for 3 seconds. The application can also ask the firmware how many LEDs it was built for, to catch a mismatch with `config.py`.
4. **Rendering**: the ESP32 sketch writes the colours to the strip with the Adafruit NeoPixel library.

## Features

- Live preview and settings in a **PyQt6** interface, with light and dark themes and an optional tray icon.
- **Presets** (for example *Film* and *Gaming*) that change smoothing, snap threshold and frame rate, saved to `presets.json`.
- **Per-application profiles**: the active preset can switch automatically according to the foreground process (Windows).
- A **calibration tool** (`debug_gui.py`) to light each side of the strip, check the physical LED order and tune the sampling depth while seeing the sampled area.
- Diagnostic scripts to test the connection, the side order, single colours, a rainbow sweep and stability.

The application is **Windows-only** (it uses `pywin32` for foreground-process detection and Windows performance counters for the GPU memory readout).

## Hardware

- An ESP32 board
- A WS2812B strip; the default configuration is 60 LEDs: 17 on top, 17 on the bottom and 13 on each side
- The strip's data line on **GPIO 5**
- A suitable 5 V power supply for the strip (do not power a long strip from the board's pin)

The strip starts at the top-left corner and runs clockwise: top, right, bottom (reversed), left (reversed).

## Setup

**1. Firmware**

- Open [`firmware/esp32_ambient_light_140hz`](firmware/esp32_ambient_light_140hz/esp32_ambient_light_140hz.ino) in the Arduino IDE.
- Install the **Adafruit NeoPixel** library.
- Set `LED_COUNT` to match `LED_TOTAL` in `config.py`, then upload the sketch.

A simpler sketch is in [`firmware/esp32_ambient_light_basic`](firmware/esp32_ambient_light_basic/esp32_ambient_light_basic.ino).

**2. Application**

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Edit `config.py`: the LED counts per side, `SERIAL_PORT` (for example `COM4`) and, if needed, the smoothing and colour settings.

## Running

Check the hardware first:

```bash
python test_connessione.py     # red, green, blue in sequence, then off
python test_sides.py           # each side in a different colour
```

If the colours come out in the wrong order (for example red shows as green), change the colour order in the sketch.

Then start the application:

```bash
python main.py
```

Without the ESP32 connected the application still starts, in **preview mode** (interface only).

## Project structure

| File | Content |
|---|---|
| `main.py` | Application controller |
| `ui.py` | PyQt6 interface (preview, settings, presets) |
| `utils.py` | Screen capture, colour computation, smoothing, black-bar detection |
| `serial_comm.py` | Serial protocol and connection handling |
| `config.py` | LED layout and signal-processing parameters |
| `presets.py`, `presets.json` | Saving and loading presets |
| `app_detect.py` | Foreground-process detection for per-app profiles |
| `gpu_monitor.py` | GPU memory readout (Windows) |
| `debug_gui.py` | Strip calibration tool |
| `firmware/` | ESP32 sketches |
| `test_*.py` | Hardware diagnostic scripts |
