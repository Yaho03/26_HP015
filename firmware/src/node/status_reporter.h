#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>
#include <WiFi.h>
#include <PubSubClient.h>

#include "mqtt/envelope.h"
#include "mqtt/topics.h"

namespace hp015::node {

// 노드 상태(배터리/RSSI/uptime/센서 온라인 상태) 주기적 전송 + LWT 등록 (이슈 #45).
// sensors/{node_id}/status 토픽으로 publish. 04_DATA_CONTRACT.md 섹션 7.2 기준.
class StatusReporter {
 public:
	static constexpr unsigned long DEFAULT_INTERVAL_MS = 10000;

	StatusReporter(const char* node_id, PubSubClient& mqtt, uint8_t battery_adc_pin = 34)
	    : node_id_(node_id), mqtt_(mqtt), battery_adc_pin_(battery_adc_pin),
	      interval_ms_(DEFAULT_INTERVAL_MS), last_send_ms_(0) {}

	// LWT는 PubSubClient::connect()의 will 인자로만 설정 가능한 라이브러리 제약
	// 때문에, MQTT 연결 시점에 main.cpp에서 직접 등록한다 (이슈 #107).
	void begin() {
		pinMode(battery_adc_pin_, INPUT);
	}

	void setSensorList(const char* const* sensors_online, size_t count) {
		sensors_online_ = sensors_online;
		sensors_online_count_ = count;
	}

	void setIntervalMs(unsigned long ms) { interval_ms_ = ms; }

	bool tick() {
		if (millis() - last_send_ms_ < interval_ms_) return false;
		last_send_ms_ = millis();
		publish();
		return true;
	}

	void publish() {
		JsonDocument doc;
		hp015::envelope::fillCommon(doc, node_id_, hp015::envelope::isoNow().c_str());
		JsonObject data = doc["data"].to<JsonObject>();
		data["battery_pct"]     = readBatteryPct();
		data["wifi_rssi_dbm"]   = WiFi.RSSI();
		data["uptime_s"]        = (long)(millis() / 1000);
		data["free_heap_bytes"] = (long)ESP.getFreeHeap();
		JsonArray online = data["sensors_online"].to<JsonArray>();
		for (size_t i = 0; i < sensors_online_count_; i++) online.add(sensors_online_[i]);
		JsonArray err = data["sensors_error"].to<JsonArray>();

		char payload[512];
		serializeJson(doc, payload, sizeof(payload));
		char topic[64];
		snprintf(topic, sizeof(topic), hp015::topics::SENSORS_STATUS, node_id_);
		mqtt_.publish(topic, payload, true);
	}

	int readBatteryPct() const {
		int raw = analogRead(battery_adc_pin_);
		float voltage = (raw / 4095.0f) * 3.3f * 2.0f;
		float pct = (voltage - 3.0f) / (4.2f - 3.0f) * 100.0f;
		if (pct < 0) return 0;
		if (pct > 100) return 100;
		return (int)pct;
	}

 private:
	const char* node_id_;
	PubSubClient& mqtt_;
	uint8_t battery_adc_pin_;
	unsigned long interval_ms_;
	unsigned long last_send_ms_;
	const char* const* sensors_online_ = nullptr;
	size_t sensors_online_count_ = 0;
};

}  // namespace hp015::node
