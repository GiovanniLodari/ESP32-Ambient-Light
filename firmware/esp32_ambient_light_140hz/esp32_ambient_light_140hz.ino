// =============================================================================
// esp32_ambient_light_140hz.ino
// Protocollo: MAGIC(4) + NUM_LED(2 BE) + RGB×N + CRC8
// Rendering: lerp interno a 120Hz indipendente dalla ricezione seriale
// =============================================================================

#include <Adafruit_NeoPixel.h>

// --- Configurazione hardware ---
#define LED_PIN       5
#define LED_COUNT     60
#define BAUD_RATE     460800

// --- Lerp interno ---
// Quanti step di interpolazione fare tra un pacchetto e il successivo.
// A 30fps Python + LERP_STEPS=4 → rendering a 120Hz
// Aumenta per transizioni più morbide, diminuisci se vedi lag
// Lerp disabilitato: colori applicati istantaneamente al ricevimento pacchetto
// Le transizioni morbide sono gestite interamente da Python (SMOOTHING_FACTOR)
#define LERP_STEPS        1
#define LERP_INTERVAL_MS  1

// --- Timeout: spegni se non arrivano pacchetti ---
#define TIMEOUT_MS   3000

Adafruit_NeoPixel strip(LED_COUNT, LED_PIN, NEO_GRB + NEO_KHZ800);

// --- Stato colori ---
// current: colore attualmente mostrato (fixed point ×256 per precisione)
// target:  ultimo colore ricevuto via seriale
int32_t cur_r[LED_COUNT], cur_g[LED_COUNT], cur_b[LED_COUNT];
uint8_t tgt_r[LED_COUNT], tgt_g[LED_COUNT], tgt_b[LED_COUNT];

// --- Parser seriale a macchina a stati ---
static const uint8_t MAGIC[4] = {0x41, 0x64, 0x61, 0x6C};

// Comando di interrogazione: un solo byte, distinto da MAGIC[0] (0x41) così
// non interferisce col matching del protocollo colori. Risposta: "LED" +
// LED_COUNT su 2 byte big-endian (5 byte totali) — usato da Python per
// verificare che config.py sia allineato al firmware realmente caricato.
#define LED_COUNT_QUERY 0x3F  // '?'

enum Stato { ATTENDI_MAGIC, LEGGI_HI, LEGGI_LO, LEGGI_RGB, LEGGI_CRC };
Stato stato = ATTENDI_MAGIC;
uint8_t magic_idx = 0;
uint16_t num_led = 0, led_idx = 0;
uint8_t rgb_sub = 0;
uint8_t buf_r, buf_g;
uint8_t crc_calc = 0;
uint8_t tmp_r[LED_COUNT], tmp_g[LED_COUNT], tmp_b[LED_COUNT];

// --- Timing ---
unsigned long ultimo_pacchetto = 0;
unsigned long ultimo_lerp = 0;
uint8_t lerp_step = 0;

// --- CRC8 (Dallas/Maxim, poly 0x07) ---
uint8_t crc8_byte(uint8_t crc, uint8_t byte) {
  crc ^= byte;
  for (uint8_t i = 0; i < 8; i++)
    crc = (crc & 0x80) ? ((crc << 1) ^ 0x07) : (crc << 1);
  return crc;
}

// --- Lerp fixed-point: avanza current verso target di 1/LERP_STEPS ---
void lerp_step_avanza() {
  for (int i = 0; i < LED_COUNT; i++) {
    int32_t tr = (int32_t)tgt_r[i] << 8;
    int32_t tg = (int32_t)tgt_g[i] << 8;
    int32_t tb = (int32_t)tgt_b[i] << 8;
    cur_r[i] += (tr - cur_r[i]) / LERP_STEPS;
    cur_g[i] += (tg - cur_g[i]) / LERP_STEPS;
    cur_b[i] += (tb - cur_b[i]) / LERP_STEPS;
  }
}

void applica_al_led() {
  for (int i = 0; i < LED_COUNT; i++)
    strip.setPixelColor(i, cur_r[i] >> 8, cur_g[i] >> 8, cur_b[i] >> 8);
  strip.show();
}

void spegni_tutto() {
  for (int i = 0; i < LED_COUNT; i++) {
    tgt_r[i] = tgt_g[i] = tgt_b[i] = 0;
  }
}

void setup() {
  Serial.begin(BAUD_RATE);
  strip.begin();
  strip.setBrightness(255);
  strip.clear();
  strip.show();
  memset(cur_r, 0, sizeof(cur_r));
  memset(cur_g, 0, sizeof(cur_g));
  memset(cur_b, 0, sizeof(cur_b));
  memset(tgt_r, 0, sizeof(tgt_r));
  memset(tgt_g, 0, sizeof(tgt_g));
  memset(tgt_b, 0, sizeof(tgt_b));
  ultimo_pacchetto = millis();
  ultimo_lerp = millis();
}

void loop() {
  // --- 1. Leggi seriale (non bloccante) ---
  while (Serial.available()) {
    uint8_t b = Serial.read();
    switch (stato) {

      case ATTENDI_MAGIC:
        if (b == LED_COUNT_QUERY) {
          Serial.write((const uint8_t*)"LED", 3);
          Serial.write((uint8_t)(LED_COUNT >> 8));
          Serial.write((uint8_t)(LED_COUNT & 0xFF));
          magic_idx = 0;
        } else if (b == MAGIC[magic_idx]) {
          magic_idx++;
          if (magic_idx == 4) { stato = LEGGI_HI; magic_idx = 0; crc_calc = 0; }
        } else {
          magic_idx = (b == MAGIC[0]) ? 1 : 0;
        }
        break;

      case LEGGI_HI:
        num_led = (uint16_t)b << 8;
        crc_calc = crc8_byte(crc_calc, b);
        stato = LEGGI_LO;
        break;

      case LEGGI_LO:
        num_led |= b;
        crc_calc = crc8_byte(crc_calc, b);
        if (num_led == 0 || num_led > LED_COUNT) { stato = ATTENDI_MAGIC; break; }
        led_idx = 0; rgb_sub = 0;
        stato = LEGGI_RGB;
        break;

      case LEGGI_RGB:
        crc_calc = crc8_byte(crc_calc, b);
        if      (rgb_sub == 0) { buf_r = b; rgb_sub = 1; }
        else if (rgb_sub == 1) { buf_g = b; rgb_sub = 2; }
        else {
          tmp_r[led_idx] = buf_r;
          tmp_g[led_idx] = buf_g;
          tmp_b[led_idx] = b;
          rgb_sub = 0;
          led_idx++;
          if (led_idx >= num_led) stato = LEGGI_CRC;
        }
        break;

      case LEGGI_CRC:
        if (b == crc_calc) {
          // Pacchetto valido: aggiorna i target
          for (uint16_t i = 0; i < num_led; i++) {
            tgt_r[i] = tmp_r[i];
            tgt_g[i] = tmp_g[i];
            tgt_b[i] = tmp_b[i];
          }
          ultimo_pacchetto = millis();
        }
        stato = ATTENDI_MAGIC;
        break;
    }
  }

  // --- 2. Timeout: avvia transizione verso nero ---
  if (millis() - ultimo_pacchetto > TIMEOUT_MS) {
    spegni_tutto();
  }

  // --- 3. Lerp interno a ~120Hz ---
  if (millis() - ultimo_lerp >= LERP_INTERVAL_MS) {
    ultimo_lerp = millis();
    lerp_step_avanza();
    applica_al_led();
  }
}