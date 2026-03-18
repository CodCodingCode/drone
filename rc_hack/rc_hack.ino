/*
 * RC Controller Hack — Arduino Nano 33 BLE Sense Lite
 *
 * Receives commands over USB serial from Python,
 * outputs PWM on 4 pins to simulate joystick positions.
 *
 * Wiring:
 *   D3  -> Throttle (left stick vertical)
 *   D5  -> Yaw      (left stick horizontal)
 *   D6  -> Pitch    (right stick vertical)
 *   D9  -> Roll     (right stick horizontal)
 *   GND -> RC board GND
 *
 * Protocol (from Python):
 *   Byte 0: 0xAA (sync)
 *   Byte 1: throttle  (0-255, 128=center)
 *   Byte 2: yaw       (0-255, 128=center)
 *   Byte 3: pitch     (0-255, 128=center)
 *   Byte 4: roll      (0-255, 128=center)
 *   Arduino replies: 0x55 (ACK)
 *
 * PWM output is smoothed by the RC board's input capacitance,
 * acting as a poor-man's DAC. If the RC reads jittery values,
 * add a simple RC filter: 1k resistor + 0.1uF cap on each pin.
 */

#define PIN_THROTTLE 3
#define PIN_YAW      5
#define PIN_PITCH    6
#define PIN_ROLL     9

#define SYNC_BYTE    0xAA
#define ACK_BYTE     0x55
#define CENTER       128

// Current stick values
uint8_t throttle = 0;    // throttle defaults to 0 (not center!)
uint8_t yaw      = CENTER;
uint8_t pitch    = CENTER;
uint8_t roll     = CENTER;

// Watchdog: if no command received in 500ms, center all sticks
unsigned long lastCmdTime = 0;
#define WATCHDOG_MS 500

void setup() {
  Serial.begin(115200);

  pinMode(PIN_THROTTLE, OUTPUT);
  pinMode(PIN_YAW, OUTPUT);
  pinMode(PIN_PITCH, OUTPUT);
  pinMode(PIN_ROLL, OUTPUT);

  // Start with safe values
  analogWrite(PIN_THROTTLE, 0);
  analogWrite(PIN_YAW, CENTER);
  analogWrite(PIN_PITCH, CENTER);
  analogWrite(PIN_ROLL, CENTER);

  lastCmdTime = millis();
}

void loop() {
  // Read serial commands
  if (Serial.available() >= 5) {
    uint8_t buf[5];
    buf[0] = Serial.read();

    if (buf[0] == SYNC_BYTE) {
      buf[1] = Serial.read();
      buf[2] = Serial.read();
      buf[3] = Serial.read();
      buf[4] = Serial.read();

      throttle = buf[1];
      yaw      = buf[2];
      pitch    = buf[3];
      roll     = buf[4];

      lastCmdTime = millis();
      Serial.write(ACK_BYTE);
    } else {
      // Bad sync — flush buffer to re-align
      while (Serial.available()) Serial.read();
    }
  }

  // Watchdog: kill throttle if no commands
  if (millis() - lastCmdTime > WATCHDOG_MS) {
    throttle = 0;
    yaw = CENTER;
    pitch = CENTER;
    roll = CENTER;
  }

  // Output PWM
  analogWrite(PIN_THROTTLE, throttle);
  analogWrite(PIN_YAW, yaw);
  analogWrite(PIN_PITCH, pitch);
  analogWrite(PIN_ROLL, roll);

  delay(1);  // ~1kHz update rate
}
