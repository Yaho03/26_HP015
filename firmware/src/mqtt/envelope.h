#pragma once

// MQTT envelope 생성 (이슈 #44, 04_DATA_CONTRACT.md 섹션 4).
// 템플릿 기반 헬퍼 — ArduinoJson Document 를 받아 공통 필드를 채운다.
// message_id = "{boot_id}-{sequence}". boot_id는 부팅 시 1회만 생성되고
// (efuse MAC + 하드웨어 난수) 이후 메시지마다 순번만 붙는다 — millis() 기반이면
// 재부팅마다 0부터 재시작해 ID가 겹치고, 백엔드 processed_messages가 재부팅 직후
// 데이터를 전부 중복으로 오판해 조용히 드롭하는 문제가 있었다 (이슈 #104).

#include <Arduino.h>
#include <ArduinoJson.h>
#include <esp_system.h>
#include "topics.h"

namespace hp015::envelope {

inline const String& bootId() {
	static String id;
	static bool initialized = false;
	if (!initialized) {
		uint64_t mac = ESP.getEfuseMac();
		uint32_t rnd = esp_random();
		char buf[24];
		snprintf(buf, sizeof(buf), "%04X%08X-%08lX",
		         (unsigned)(mac >> 32), (unsigned)(mac & 0xFFFFFFFFu),
		         (unsigned long)rnd);
		id = String(buf);
		initialized = true;
	}
	return id;
}

inline String makeMessageId() {
	static uint32_t sequence = 0;
	char buf[48];
	snprintf(buf, sizeof(buf), "%s-%lu", bootId().c_str(), (unsigned long)sequence++);
	return String(buf);
}

// UTC 벽시계 기준 ISO8601 문자열 생성. NTP 동기화(main.cpp setup(), 이슈 #107)가
// 끝난 뒤에야 실제 날짜/시각이 맞다 — 동기화 전에는 1970-01-01 근처 값이 나온다.
inline String isoNow() {
	struct timeval tv;
	gettimeofday(&tv, nullptr);
	time_t seconds = tv.tv_sec;
	struct tm timeinfo;
	gmtime_r(&seconds, &timeinfo);
	char buf[32];
	snprintf(buf, sizeof(buf), "%04d-%02d-%02dT%02d:%02d:%02d.%03ldZ",
	         timeinfo.tm_year + 1900, timeinfo.tm_mon + 1, timeinfo.tm_mday,
	         timeinfo.tm_hour, timeinfo.tm_min, timeinfo.tm_sec,
	         (long)(tv.tv_usec / 1000));
	return String(buf);
}

inline void fillCommon(JsonDocument& doc, const char* nodeId, const char* sampledAt) {
	doc["schema_version"] = hp015::topics::SCHEMA_VERSION;
	doc["message_id"]     = makeMessageId();
	doc["node_id"]        = nodeId;
	doc["sampled_at"]     = sampledAt;
	doc["source_mode"]    = "live";
	doc["simulation"]     = nullptr;
}

inline void fillConnection(JsonDocument& doc, const char* nodeId,
                           const char* status, const char* reason) {
	doc["schema_version"] = hp015::topics::SCHEMA_VERSION;
	doc["node_id"]        = nodeId;
	doc["status"]         = status;
	doc["reason"]         = reason;
	doc["boot_id"]        = bootId();
	doc["timestamp"]      = isoNow();
}

}  // namespace hp015::envelope
