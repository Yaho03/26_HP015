#pragma once

#include <Arduino.h>

namespace Ulid {

// 현재 NTP Unix timestamp(ms)를 기반으로 ULID 생성
String generate();

// 원하는 timestamp(ms)로 ULID 생성
String generate(uint64_t timestampMs);

}  // namespace Ulid