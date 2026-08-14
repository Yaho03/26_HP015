#pragma once

// SEN0322 O₂ 센서 드라이버 인터페이스 (이슈 #42, P0-critical, safety-critical).
//
// SEN0322는 I2C (기본 주소 0x73) 로 연결되며, 가스 농도를 % 단위로 반환한다.
// 응답 시간 최대 15초 (06_ALERT_RULES 섹션 6 참고).
//
// #113: O2 reading is safety-critical. I2C/read failures must be reported to
// the caller instead of returning a cached "normal air" value.

#include <Arduino.h>
#include <Wire.h>

namespace hp015::sensors {

class Sen0322 {
 public:
	static constexpr uint8_t DEFAULT_I2C_ADDRESS = 0x73;

	explicit Sen0322(uint8_t address = DEFAULT_I2C_ADDRESS, TwoWire* wire = &Wire)
	    : address_(address), wire_(wire), last_pct_(0.0f), last_read_ms_(0) {}

	bool begin() {
		wire_->beginTransmission(address_);
		return wire_->endTransmission() == 0;
	}

	bool read(float& out_pct) {
	#if defined(HP015_SIMULATE_O2)
		out_pct = last_pct_;
		last_read_ms_ = millis();
		return true;
	#else
		wire_->beginTransmission(address_);
		wire_->write(DATA_REGISTER);
		if (wire_->endTransmission(false) != 0) {
			return false;
		}

		const uint8_t received = wire_->requestFrom(address_, (uint8_t)3);
		if (received != 3 || wire_->available() < 3) {
			return false;
		}

		const uint8_t b0 = wire_->read();
		const uint8_t b1 = wire_->read();
		const uint8_t b2 = wire_->read();

		// DFRobot SEN0322 data register format: O2 %vol = b0 + b1/10 + b2/100.
		// Linux IIO sen0322 driver documents the same formula for registers 0x03..0x05.
		const float pct = (float)b0 + ((float)b1 / 10.0f) + ((float)b2 / 100.0f);
		if (pct < 0.0f || pct > MAX_VALID_PCT) {
			return false;
		}

		out_pct = pct;
		last_pct_ = pct;
		last_read_ms_ = millis();
		return true;
	#endif
	}

#if defined(HP015_SIMULATE_O2)
	void setSimulatedValue(float pct) { last_pct_ = pct; }
#endif

	bool isFresh(unsigned long max_age_ms = 5000) const {
		return (millis() - last_read_ms_) < max_age_ms;
	}

 private:
	static constexpr uint8_t DATA_REGISTER = 0x03;
	static constexpr float MAX_VALID_PCT = 30.0f;

	uint8_t address_;
	TwoWire* wire_;
	float last_pct_;
	unsigned long last_read_ms_;
};

}  // namespace hp015::sensors
