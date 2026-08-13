#pragma once

// MQTT envelope 생성 (이슈 #44, 04_DATA_CONTRACT.md 섹션 4).
// 템플릿 기반 헬퍼 — ArduinoJson Document 를 받아 공통 필드를 채운다.
//
// message_id/boot_id는 schemas/*.schema.json이 ULID 패턴
// (^[0-7][0-9A-HJKMNP-TV-Z]{25}$)을 강제하므로 실제 ULID(48bit 시각 +
// 80bit 하드웨어 난수, Crockford Base32)로 생성한다 — boot_id는 부팅 시
// 1회 생성 후 캐싱(재부팅마다 달라져 이슈 #104의 재사용 방지 목적도 그대로
// 만족), message_id는 매 호출 시 새로 생성(80bit 난수라 재부팅 여부와
// 무관하게 항상 고유).

#include <Arduino.h>
#include <ArduinoJson.h>
#include <esp_system.h>
#include "topics.h"

namespace hp015::envelope {

namespace detail {

inline String crockford32(uint64_t value, int chars) {
	static const char* ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
	char buf[17];
	buf[chars] = '\0';
	for (int i = chars - 1; i >= 0; i--) {
		buf[i] = ALPHABET[value & 0x1F];
		value >>= 5;
	}
	return String(buf);
}

inline uint64_t random64() {
	return (((uint64_t)esp_random()) << 32) | esp_random();
}

// ULID = 48bit 밀리초 타임스탬프(10 base32 문자) + 80bit 난수(16 base32 문자).
// 80bit은 uint64_t 범위를 넘으므로 40bit씩 두 번(64bit 난수에서 하위 40bit만 사용)
// 나눠 생성한다.
inline String generateUlid() {
	struct timeval tv;
	gettimeofday(&tv, nullptr);
	uint64_t ms = (uint64_t)tv.tv_sec * 1000ULL + (tv.tv_usec / 1000);
	String ts_part = crockford32(ms, 10);
	String rand_part_1 = crockford32(random64() & 0xFFFFFFFFFFULL, 8);
	String rand_part_2 = crockford32(random64() & 0xFFFFFFFFFFULL, 8);
	return ts_part + rand_part_1 + rand_part_2;
}

}  // namespace detail

inline const String& bootId() {
	static String id;
	static bool initialized = false;
	if (!initialized) {
		id = detail::generateUlid();
		initialized = true;
	}
	return id;
}

inline String makeMessageId() {
	return detail::generateUlid();
}

inline uint32_t nextSequence() {
	static uint32_t sequence = 0;
	return sequence++;
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

// syncNtp()(main.cpp)가 성공했는지 판단하는 기준과 동일 — 2020-01-01 이후면 동기화된 것으로 간주.
inline bool isTimeSynced() {
	return time(nullptr) >= 1577836800L;
}

// 센서-gas/env/status 스키마가 공통으로 요구하는 quality.sensors 6개 필드
// (mh-z19b/mq-7/mq-136/mq-2/bme680/ads1115, 03_HARDWARE_DESIGN.md 회로 기준).
// MQ 계열 3개는 ADS1115 채널로 공유 배선되어 있어 연결 여부/교정 상태를 함께 쓴다.
struct SensorQuality {
	bool mhz19b_ok = true;
	bool bme680_ok = false;
	bool ads1115_ok = false;
	bool mq_calibrated = false;
};

inline void fillCommon(JsonDocument& doc, const char* nodeId, const char* sampledAt,
                        const SensorQuality& quality) {
	doc["schema_version"] = hp015::topics::SCHEMA_VERSION;
	doc["message_id"]     = makeMessageId();
	doc["node_id"]        = nodeId;
	doc["boot_id"]        = bootId();
	doc["sequence"]       = nextSequence();
	doc["sampled_at"]     = sampledAt;
	doc["published_at"]   = isoNow();
	doc["source_mode"]    = "live";
	doc["simulation"]     = nullptr;

	JsonObject q = doc["quality"].to<JsonObject>();
	q["message_status"] = "complete";
	q["time_synced"] = isTimeSynced();
	JsonObject sensors = q["sensors"].to<JsonObject>();
	sensors["mh-z19b"] = quality.mhz19b_ok ? "valid" : "not_connected";
	const char* mq_status = !quality.ads1115_ok ? "not_connected"
	                         : (quality.mq_calibrated ? "valid" : "uncalibrated");
	sensors["mq-7"] = mq_status;
	sensors["mq-136"] = mq_status;
	sensors["mq-2"] = mq_status;
	sensors["bme680"] = quality.bme680_ok ? "valid" : "not_connected";
	sensors["ads1115"] = quality.ads1115_ok ? "valid" : "not_connected";
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
