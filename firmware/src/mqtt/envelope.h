#pragma once

// MQTT envelope 생성 (이슈 #44, 04_DATA_CONTRACT.md 섹션 4).
// 템플릿 기반 헬퍼 — ArduinoJson Document 를 받아 공통 필드를 채운다.
// message_id 로 ULID 를 써야 하지만 ESP32 에서는 간단히 millis 기반 문자열 사용
// (FR-101 dedup은 백엔드 processed_messages 가 1차 방어).

#include <Arduino.h>
#include <ArduinoJson.h>
#include "topics.h"

namespace hp015::envelope {

inline String makeMessageId() {
	char buf[16];
	snprintf(buf, sizeof(buf), "esp_%lu", (unsigned long)millis());
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
	doc["boot_id"]        = makeMessageId();
	doc["timestamp"]      = isoNow();
}

}  // namespace hp015::envelope
