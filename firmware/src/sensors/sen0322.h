#pragma once

// SEN0322 O₂ 센서 드라이버 인터페이스 (이슈 #42, P0-critical, safety-critical).
//
// SEN0322는 I2C (기본 주소 0x73) 로 연결되며, 가스 농도를 % 단위로 반환한다.
// 응답 시간 최대 15초 (06_ALERT_RULES 섹션 6 참고).
//
// 본 헤더는 인터페이스만 제공한다 — 실제 I2C 통신 구현은 #42 에서 완성한다.
// #86 로컬 폴백은 readPercent() 가 float 을 반환한다고 가정하고 동작한다.

#include <Arduino.h>
#include <Wire.h>

namespace hp015::sensors {

class Sen0322 {
 public:
	static constexpr uint8_t DEFAULT_I2C_ADDRESS = 0x73;

	explicit Sen0322(uint8_t address = DEFAULT_I2C_ADDRESS, TwoWire* wire = &Wire)
	    : address_(address), wire_(wire), last_pct_(20.9f), last_read_ms_(0) {}

	bool begin() {
		wire_->beginTransmission(address_);
		return wire_->endTransmission() == 0;
	}

	float readPercent() {
		// TODO(#42): SEN0322 프로토콜 (reg 0x04..0x06 raw → % 변환) 구현.
		// 임시로 캐시된 값 반환. 데모 시나리오에서는 이 값을 시뮬레이션 데이터로 override.
		last_read_ms_ = millis();
		return last_pct_;
	}

	void setSimulatedValue(float pct) { last_pct_ = pct; }

	bool isFresh(unsigned long max_age_ms = 5000) const {
		return (millis() - last_read_ms_) < max_age_ms;
	}

 private:
	uint8_t address_;
	TwoWire* wire_;
	float last_pct_;
	unsigned long last_read_ms_;
};

}  // namespace hp015::sensors
