// =============================================================================
// esp32_ambilight.cpp
// Protocollo: MAGIC(4) + NUM_LED(2 BE) + RGB×N + CRC8
// Rendering: i LED si aggiornano UNA volta per pacchetto valido ricevuto.
// =============================================================================

#include <Adafruit_NeoPixel.h>

// --- Configurazione hardware ---
#define LED_PIN       5
#define LED_COUNT     60
#define BAUD_RATE     460800

// Buffer RX della seriale. Un pacchetto è 4+2+LED_COUNT*3+1 byte (187 con 60
// LED) e strip.show() blocca per ~2ms durante i quali arrivano ~90 byte: con
// il default di 256 il margine è minimo. Va impostato PRIMA di Serial.begin().
#define SERIAL_RX_BUFFER 1024

// Smoothing: gestito interamente da Python (SMOOTHING_FACTOR) — il firmware
// applica i colori ricevuti così come sono. Non c'è più nessun lerp interno
// (con LERP_STEPS=1 era un'identità, ma riscriveva comunque i LED ogni 1ms
// con gli stessi dati, tenendo il loop quasi sempre dentro strip.show()).

// --- Timeout: spegni se non arrivano pacchetti ---
#define TIMEOUT_MS   3000

Adafruit_NeoPixel strip(LED_COUNT, LED_PIN, NEO_GRB + NEO_KHZ800);

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

// --- Timing / stato ---
unsigned long ultimo_pacchetto = 0;
bool spento = true;   // true = i LED sono già stati spenti, niente show() inutili

// --- CRC8 (Dallas/Maxim, poly 0x07) ---
uint8_t crc8_byte(uint8_t crc, uint8_t byte) {
  crc ^= byte;
  for (uint8_t i = 0; i < 8; i++)
    crc = (crc & 0x80) ? ((crc << 1) ^ 0x07) : (crc << 1);
  return crc;
}

// Scrive i colori del pacchetto appena validato e li mostra (un solo show()).
// Se il pacchetto contiene meno LED di LED_COUNT gli altri restano invariati.
void applica_pacchetto(uint16_t quanti) {
  for (uint16_t i = 0; i < quanti; i++)
    strip.setPixelColor(i, tmp_r[i], tmp_g[i], tmp_b[i]);
  strip.show();
  spento = false;
}

void spegni_tutto() {
  strip.clear();
  strip.show();
  spento = true;
}

void setup() {
  Serial.setRxBufferSize(SERIAL_RX_BUFFER);
  Serial.begin(BAUD_RATE);
  strip.begin();
  strip.setBrightness(255);
  strip.clear();
  strip.show();
  ultimo_pacchetto = millis();
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
          // Pacchetto valido: mostra subito
          applica_pacchetto(num_led);
          ultimo_pacchetto = millis();
        }
        stato = ATTENDI_MAGIC;
        break;
    }
  }

  // --- 2. Timeout: nessun pacchetto da TIMEOUT_MS -> spegni (una volta sola) ---
  if (!spento && millis() - ultimo_pacchetto > TIMEOUT_MS) {
    spegni_tutto();
  }
}
