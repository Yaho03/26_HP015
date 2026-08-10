#include <Arduino.h>

#include "mqtt/envelope.h"
#include "mqtt/topics.h"
#include "sensors/sen0322.h"
#include "wearable/local_alert.h"
#include "wearable/vibration_motor.h"

// 26_HP015 firmware: 센서 노드(4) + 웨어러블 노드(1) (이슈 #36 골격, #44 envelope, #86 로컬 폴백).
//
// NODE_SENSOR / NODE_WEARABLE 은 platformio.ini 의 build_flags 로 정의된다.
// - sensor-node: 센서 읽기 + MQTT publish (#39-#45 드라이버 추가 후 확장)
// - wearable-node: O₂ 센서 읽기 + 로컬 임계값 검사 + 진동 모터 자율 구동 (#86, safety-critical)
//
// 실제 센서/네트워크 코드는 각 드라이버 이슈에서 채운다. 본 파일은 환경별 진입점만 제공.

#ifndef LED_BUILTIN
#define LED_BUILTIN 2
#endif

#if defined(NODE_WEARABLE)
static hp015::wearable::VibrationMotor vibration_motor(25);
static hp015::wearable::LocalAlert local_alert(vibration_motor);
static hp015::sensors::Sen0322 o2_sensor;
#endif

void setup() {
	Serial.begin(115200);
	pinMode(LED_BUILTIN, OUTPUT);

#if defined(NODE_SENSOR)
	Serial.println(F("26_HP015 firmware: sensor-node build"));
#elif defined(NODE_WEARABLE)
	Serial.println(F("26_HP015 firmware: wearable-node build"));
	vibration_motor.begin();
	if (o2_sensor.begin()) {
		Serial.println(F("[wearable] SEN0322 detected"));
	} else {
		Serial.println(F("[wearable] SEN0322 NOT detected — using simulated 20.9%"));
		o2_sensor.setSimulatedValue(20.9f);
	}
	Serial.println(F("[wearable] local O2 fallback armed (16.0 / 28.0 %)"));
#endif
}

float readO2() {
#if defined(NODE_WEARABLE)
	return o2_sensor.readPercent();
#else
	return 0.0f;
#endif
}

void loop() {
#if defined(NODE_WEARABLE)
	float o2 = readO2();
	bool danger = local_alert.evaluate(o2);
	if (danger) {
		Serial.printf("[wearable] LOCAL ALERT: o2=%.2f%% → 진동 구동\n", o2);
	}
	digitalWrite(LED_BUILTIN, danger ? HIGH : LOW);
	delay(500);
#else
	digitalWrite(LED_BUILTIN, HIGH);
	delay(500);
	digitalWrite(LED_BUILTIN, LOW);
	delay(500);
#endif
}
