#pragma once

#include <Arduino.h>

namespace MqttTime {

// Wi-Fi 연결 후 호출
bool sync(unsigned long timeoutMs = 15000);

// 현재 NTP 시간이 유효한지 확인
bool isSynced();

// 현재 시간을 ISO 8601 UTC + 밀리초 형식으로 반환
// 예: 2026-08-10T03:24:31.120Z
String nowIso8601Utc();

// 현재 Unix timestamp (밀리초)
uint64_t nowMs();

}  // namespace MqttTime