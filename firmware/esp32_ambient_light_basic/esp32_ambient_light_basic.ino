#include <Adafruit_NeoPixel.h>

#define LED_PIN    5
#define LED_COUNT  60          // DEVE corrispondere a LED_TOTAL in config.py
#define LUMINOSITA 80

Adafruit_NeoPixel strip(LED_COUNT, LED_PIN, NEO_GRB + NEO_KHZ800);

static const uint8_t MAGIC[4] = { 0x41, 0x64, 0x61, 0x6C }; // "Adal"

#define TIMEOUT_MS 3000

enum Stato {
  ATTESA_MAGIC_0, ATTESA_MAGIC_1, ATTESA_MAGIC_2, ATTESA_MAGIC_3,
  ATTESA_HI, ATTESA_LO, RICEZIONE_DATI, ATTESA_CRC
};

Stato    stato          = ATTESA_MAGIC_0;
uint16_t num_led_atteso = 0;
uint16_t byte_ricevuti  = 0;
uint8_t  buf[2 + LED_COUNT * 3];

unsigned long ultimo_valido = 0;
bool segnale_attivo = false;

uint8_t crc8(const uint8_t* data, size_t len) {
  uint8_t crc = 0;
  for (size_t i = 0; i < len; i++) {
    crc ^= data[i];
    for (uint8_t b = 0; b < 8; b++)
      crc = (crc & 0x80) ? (crc << 1) ^ 0x07 : crc << 1;
  }
  return crc;
}

void spegni() { strip.clear(); strip.show(); }

void setup() {
  Serial.begin(115200);
  strip.begin();
  strip.setBrightness(LUMINOSITA);
  spegni();
  ultimo_valido = millis();
  Serial.println("[ESP32] Pronto");
}

void loop() {
  unsigned long now = millis();

  // Timeout: nessun segnale → spegni
  if (segnale_attivo && now - ultimo_valido > TIMEOUT_MS) {
    segnale_attivo = false;
    spegni();
    stato = ATTESA_MAGIC_0;
    Serial.println("[ESP32] Timeout — spento");
  }

  if (!Serial.available()) return;
  uint8_t c = Serial.read();

  switch (stato) {
    case ATTESA_MAGIC_0: stato = (c == MAGIC[0]) ? ATTESA_MAGIC_1 : ATTESA_MAGIC_0; break;
    case ATTESA_MAGIC_1: stato = (c == MAGIC[1]) ? ATTESA_MAGIC_2 : ATTESA_MAGIC_0; break;
    case ATTESA_MAGIC_2: stato = (c == MAGIC[2]) ? ATTESA_MAGIC_3 : ATTESA_MAGIC_0; break;
    case ATTESA_MAGIC_3: stato = (c == MAGIC[3]) ? ATTESA_HI       : ATTESA_MAGIC_0; break;

    case ATTESA_HI:
      buf[0] = c;
      stato = ATTESA_LO;
      break;

    case ATTESA_LO:
      buf[1] = c;
      num_led_atteso = ((uint16_t)buf[0] << 8) | buf[1];
      if (num_led_atteso != LED_COUNT) {
        Serial.print("[ESP32] Mismatch: ricevuto ");
        Serial.print(num_led_atteso);
        Serial.print(" atteso ");
        Serial.println(LED_COUNT);
        stato = ATTESA_MAGIC_0;
      } else {
        byte_ricevuti = 0;
        stato = RICEZIONE_DATI;
      }
      break;

    case RICEZIONE_DATI:
      buf[2 + byte_ricevuti++] = c;
      if (byte_ricevuti >= (uint16_t)num_led_atteso * 3)
        stato = ATTESA_CRC;
      break;

    case ATTESA_CRC: {
      uint8_t crc_calc = crc8(buf, 2 + num_led_atteso * 3);
      if (c == crc_calc) {
        for (uint16_t i = 0; i < num_led_atteso; i++) {
          strip.setPixelColor(i, strip.Color(
            buf[2 + i * 3],
            buf[2 + i * 3 + 1],
            buf[2 + i * 3 + 2]
          ));
        }
        strip.show();
        ultimo_valido = now;
        segnale_attivo = true;
      } else {
        Serial.println("[ESP32] CRC errato — scartato");
      }
      stato = ATTESA_MAGIC_0;
      break;
    }

    default: stato = ATTESA_MAGIC_0;
  }
}