#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <esp_task_wdt.h>
#include <time.h>

#include "mqtt/envelope.h"
#include "mqtt/topics.h"
#include "node/status_reporter.h"
#include "sensors/ads1115.h"
#include "sensors/bme680.h"
#include "sensors/mhz19b.h"
#include "sensors/sen0322.h"
#include "wearable/local_alert.h"
#include "wearable/vibration_motor.h"
#include "wifi_credentials.h"

// 26_HP015 firmware: 센서 노드(4) + 웨어러블 노드(1) (이슈 #36 골격, #44 envelope, #86 로컬 폴백, #107 WiFi/MQTT 배선).
//
// NODE_SENSOR / NODE_WEARABLE 은 platformio.ini 의 build_flags 로 정의된다.
// - sensor-node: WiFi/MQTT 연결 + 가스/환경/상태 주기 publish (04_DATA_CONTRACT.md)
// - wearable-node: O₂ 센서 읽기 + 로컬 임계값 검사 + 진동 모터 자율 구동 (#86, safety-critical)
//   (웨어러블의 MQTT 배선은 #107 범위 밖 — 로컬 폴백 경보는 브로커 없이도 동작해야 하므로 기존 동작 유지)

#ifndef LED_BUILTIN
#define LED_BUILTIN 2
#endif

#if defined(NODE_SENSOR)

// 스케줄 주기 (04_DATA_CONTRACT.md 3.2 QoS 정책과 별개로, 발행 주기는 이슈 #107 수정안 기준).
static constexpr unsigned long GAS_INTERVAL_MS    = 1000;   // 1Hz
static constexpr unsigned long ENV_INTERVAL_MS     = 5000;   // 0.2Hz
static constexpr unsigned long WDT_TIMEOUT_S       = 15;
static constexpr unsigned long WIFI_RETRY_MAX_MS   = 30000;
static constexpr unsigned long NTP_SYNC_TIMEOUT_MS = 15000;

static WiFiClient wifi_client;
static PubSubClient mqtt_client(wifi_client);

static hp015::sensors::Mhz19b co2_sensor;
static hp015::sensors::Bme680 bme_sensor;
static hp015::sensors::Ads1115 ads;
static hp015::sensors::MqSensor co_sensor;
static hp015::sensors::MqSensor h2s_sensor;
static hp015::sensors::MqSensor mq2_sensor;
static hp015::node::StatusReporter status_reporter(NODE_ID, mqtt_client);

static const char* const kSensorsOnline[] = {"mh-z19b", "bme680", "ads1115"};

// setup()에서 센서 감지 결과로 채워 fillCommon()의 quality.sensors에 반영한다 (이슈 #107 리뷰).
static hp015::envelope::SensorQuality g_quality;

static unsigned long last_gas_ms = 0;
static unsigned long last_env_ms = 0;

static void connectWiFi() {
	WiFi.mode(WIFI_STA);
	WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
	Serial.printf("[wifi] connecting to %s", WIFI_SSID);

	unsigned long start = millis();
	unsigned long backoff_ms = 500;
	while (WiFi.status() != WL_CONNECTED) {
		esp_task_wdt_reset();
		delay(backoff_ms);
		Serial.print(".");
		if (millis() - start > WIFI_RETRY_MAX_MS) {
			Serial.println(F("\n[wifi] retrying (backoff)"));
			WiFi.disconnect();
			WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
			start = millis();
			backoff_ms = min(backoff_ms * 2, 5000UL);
		}
	}
	Serial.printf("\n[wifi] connected, IP=%s\n", WiFi.localIP().toString().c_str());
}

// NTP 동기화 — envelope::isoNow()가 실제 UTC 벽시계를 반환하려면 필수 (이슈 #103).
static void syncNtp() {
	configTime(0, 0, "pool.ntp.org", "time.nist.gov");
	Serial.print(F("[ntp] syncing"));
	unsigned long start = millis();
	// 동기화 전 time()은 1970 근처 값을 반환하므로, 2020년 이후 값이 나올 때까지 대기.
	while (time(nullptr) < 1577836800L) {  // 2020-01-01
		esp_task_wdt_reset();
		delay(200);
		Serial.print(".");
		if (millis() - start > NTP_SYNC_TIMEOUT_MS) {
			Serial.println(F("\n[ntp] sync timeout — sampled_at may be inaccurate"));
			return;
		}
	}
	Serial.println(F("\n[ntp] synced"));
}

static void publishConnection(const char* status, const char* reason) {
	JsonDocument doc;
	hp015::envelope::fillConnection(doc, NODE_ID, status, reason);
	char payload[256];
	serializeJson(doc, payload, sizeof(payload));
	char topic[64];
	snprintf(topic, sizeof(topic), hp015::topics::NODE_CONNECTION, NODE_ID);
	mqtt_client.publish(topic, payload, true);
}

static void connectMqtt() {
	mqtt_client.setServer(MQTT_HOST, MQTT_PORT);

	JsonDocument will_doc;
	hp015::envelope::fillConnection(will_doc, NODE_ID, "offline", "lwt");
	char will_payload[256];
	serializeJson(will_doc, will_payload, sizeof(will_payload));
	char will_topic[64];
	snprintf(will_topic, sizeof(will_topic), hp015::topics::NODE_CONNECTION, NODE_ID);

	while (!mqtt_client.connected()) {
		esp_task_wdt_reset();
		Serial.print(F("[mqtt] connecting..."));
		String client_id = String(NODE_ID) + "-" + hp015::envelope::bootId();
		bool ok = mqtt_client.connect(client_id.c_str(), MQTT_USERNAME, MQTT_PASSWORD,
		                               will_topic, /*willQos=*/1, /*willRetain=*/true,
		                               will_payload);
		if (ok) {
			Serial.println(F(" connected"));
			// node-connection.schema.json의 reason enum: connect|lwt|timeout (이슈 #107 리뷰).
			publishConnection("online", "connect");
		} else {
			Serial.printf(" failed, rc=%d — retry in 5s\n", mqtt_client.state());
			delay(5000);
		}
	}
}

static void publishGas() {
	JsonDocument doc;
	hp015::envelope::fillCommon(doc, NODE_ID, hp015::envelope::isoNow().c_str(), g_quality);
	JsonObject data = doc["data"].to<JsonObject>();

	data["co2_ppm"] = co2_sensor.readCo2Ppm();

	int16_t co_raw = ads.readChannel(0);
	co_sensor.updateFromVoltage(ads.lastVoltageV());
	data["co_raw_adc"]            = co_raw;
	data["co_voltage_v"]          = ads.lastVoltageV();
	data["co_rs_ohm"]             = co_sensor.rsOhm();
	data["co_rs_r0_ratio"]        = co_sensor.rsR0Ratio();
	data["co_estimated_ppm"]      = nullptr;
	data["co_calibration_status"] = co_sensor.isCalibrated() ? "calibrated" : "uncalibrated";

	int16_t h2s_raw = ads.readChannel(1);
	h2s_sensor.updateFromVoltage(ads.lastVoltageV());
	data["h2s_raw_adc"]            = h2s_raw;
	data["h2s_voltage_v"]          = ads.lastVoltageV();
	data["h2s_rs_ohm"]             = h2s_sensor.rsOhm();
	data["h2s_rs_r0_ratio"]        = h2s_sensor.rsR0Ratio();
	data["h2s_estimated_ppm"]      = nullptr;
	data["h2s_calibration_status"] = h2s_sensor.isCalibrated() ? "calibrated" : "uncalibrated";

	int16_t mq2_raw = ads.readChannel(2);
	mq2_sensor.updateFromVoltage(ads.lastVoltageV());
	data["mq2_raw_adc"]                  = mq2_raw;
	data["mq2_voltage_v"]                = ads.lastVoltageV();
	data["mq2_rs_ohm"]                   = mq2_sensor.rsOhm();
	data["mq2_rs_r0_ratio"]              = mq2_sensor.rsR0Ratio();
	data["mq2_estimated_concentration"]  = nullptr;
	data["mq2_calibration_status"]       = mq2_sensor.isCalibrated() ? "calibrated" : "uncalibrated";

	data["gas_resistance_ohm"] = bme_sensor.gasResistanceOhm();
	data["iaq_index"]          = bme_sensor.iaqIndex();
	data["iaq_accuracy"]       = bme_sensor.iaqAccuracy();

	char payload[768];
	serializeJson(doc, payload, sizeof(payload));
	char topic[64];
	snprintf(topic, sizeof(topic), hp015::topics::SENSORS_GAS, NODE_ID);
	mqtt_client.publish(topic, payload);
}

static void publishEnv() {
	JsonDocument doc;
	hp015::envelope::fillCommon(doc, NODE_ID, hp015::envelope::isoNow().c_str(), g_quality);
	JsonObject data = doc["data"].to<JsonObject>();
	data["temperature_c"] = bme_sensor.temperatureC();
	data["humidity_pct"]  = bme_sensor.humidityPct();
	data["pressure_hpa"]  = bme_sensor.pressureHpa();

	char payload[256];
	serializeJson(doc, payload, sizeof(payload));
	char topic[64];
	snprintf(topic, sizeof(topic), hp015::topics::SENSORS_ENV, NODE_ID);
	mqtt_client.publish(topic, payload);
}

#endif  // NODE_SENSOR

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
	esp_task_wdt_init(WDT_TIMEOUT_S, true);
	esp_task_wdt_add(NULL);

	co2_sensor.begin();
	g_quality.bme680_ok = bme_sensor.begin();
	if (!g_quality.bme680_ok) {
		Serial.println(F("[sensor] BME680 NOT detected"));
	}
	g_quality.ads1115_ok = ads.begin();
	if (!g_quality.ads1115_ok) {
		Serial.println(F("[sensor] ADS1115 NOT detected"));
	}
	status_reporter.setSensorList(kSensorsOnline, 3);
	status_reporter.setQuality(g_quality);
	status_reporter.begin();

	connectWiFi();
	syncNtp();
	connectMqtt();
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
#if defined(NODE_SENSOR)
	esp_task_wdt_reset();

	if (WiFi.status() != WL_CONNECTED) {
		connectWiFi();
	}
	if (!mqtt_client.connected()) {
		connectMqtt();
	}
	mqtt_client.loop();

	unsigned long now = millis();
	if (now - last_gas_ms >= GAS_INTERVAL_MS) {
		last_gas_ms = now;
		bme_sensor.readAll();
		publishGas();
	}
	if (now - last_env_ms >= ENV_INTERVAL_MS) {
		last_env_ms = now;
		publishEnv();
	}
	status_reporter.tick();

	digitalWrite(LED_BUILTIN, mqtt_client.connected() ? HIGH : LOW);
#elif defined(NODE_WEARABLE)
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
