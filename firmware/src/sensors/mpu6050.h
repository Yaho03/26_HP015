#pragma once

#include <Arduino.h>
#include <Wire.h>
#include <math.h>

namespace hp015::sensors {

class Mpu6050 {
 public:
	static constexpr uint8_t DEFAULT_I2C_ADDRESS = 0x68;
	static constexpr float ACCEL_RANGE_2G = 2.0f;

	explicit Mpu6050(uint8_t address = DEFAULT_I2C_ADDRESS, TwoWire* wire = &Wire)
	    : address_(address), wire_(wire), ax_(0), ay_(0), az_(9.8f), last_read_ms_(0) {}

	bool begin() {
		wire_->beginTransmission(address_);
		return wire_->endTransmission() == 0;
	}

	void readAccelGs(float& ax, float& ay, float& az) {
		// TODO(#43): 레지스터 0x3B..0x40 읽기 + ACCEL_RANGE_2G (-32768..32767 → ±2g) 변환.
		ax = ax_;
		ay = ay_;
		az = az_;
		last_read_ms_ = millis();
	}

	float accelMagnitudeG() const {
		return sqrtf(ax_ * ax_ + ay_ * ay_ + az_ * az_);
	}

	void setSimulatedAccelGs(float ax, float ay, float az) {
		ax_ = ax;
		ay_ = ay;
		az_ = az;
	}

	bool isFresh(unsigned long max_age_ms = 1000) const {
		return (millis() - last_read_ms_) < max_age_ms;
	}

 private:
	uint8_t address_;
	TwoWire* wire_;
	float ax_;
	float ay_;
	float az_;
	unsigned long last_read_ms_;
};

}  // namespace hp015::sensors
