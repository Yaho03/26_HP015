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

inline String isoNow() {
	char buf[32];
	snprintf(buf, sizeof(buf), "2026-01-01T00:00:%05lu.000Z",
	         (unsigned long)(millis() / 1000) % 100000);
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
