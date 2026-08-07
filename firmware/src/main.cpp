#include <Arduino.h>

// Minimal blink to verify the PlatformIO toolchain, build, and upload path (issue #36).
// Real sensor reads / MQTT publishing are added in follow-up issues (#39-#45, #68).
//
// NODE_SENSOR / NODE_WEARABLE are defined per environment in platformio.ini;
// used here only to print which build is running.

#ifndef LED_BUILTIN
#define LED_BUILTIN 2  // ESP32 DevKitC 온보드 LED (GPIO2)
#endif

void setup() {
	Serial.begin(115200);
	pinMode(LED_BUILTIN, OUTPUT);
#if defined(NODE_SENSOR)
	Serial.println("26_HP015 firmware: sensor-node build");
#elif defined(NODE_WEARABLE)
	Serial.println("26_HP015 firmware: wearable-node build");
#endif
}

void loop() {
	digitalWrite(LED_BUILTIN, HIGH);
	delay(500);
	digitalWrite(LED_BUILTIN, LOW);
	delay(500);
}
