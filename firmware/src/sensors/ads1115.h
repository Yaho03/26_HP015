#pragma once

#include <Arduino.h>
#include <Wire.h>

namespace hp015::sensors {

class Ads1115 {
 public:
	static constexpr uint8_t DEFAULT_I2C_ADDRESS = 0x48;

	explicit Ads1115(uint8_t address = DEFAULT_I2C_ADDRESS, TwoWire* wire = &Wire)
	    : address_(address), wire_(wire), last_raw_(0), last_voltage_v_(0.0f),
	      last_read_ms_(0) {}

	bool begin() {
		wire_->beginTransmission(address_);
		return wire_->endTransmission() == 0;
	}

	int16_t readChannel(uint8_t channel) {
		// TODO(#41): config register 설정 (PGA gain, data rate, single-shot) + conversion read.
		last_read_ms_ = millis();
		return last_raw_;
	}

	int16_t lastRaw() const { return last_raw_; }
	float lastVoltageV() const { return last_voltage_v_; }

	void setSimulated(int16_t raw, float voltage) {
		last_raw_ = raw;
		last_voltage_v_ = voltage;
		last_read_ms_ = millis();
	}

	bool isFresh(unsigned long max_age_ms = 1000) const {
		return (millis() - last_read_ms_) < max_age_ms;
	}

 private:
	uint8_t address_;
	TwoWire* wire_;
	int16_t last_raw_;
	float last_voltage_v_;
	unsigned long last_read_ms_;
};


struct MqCalibration {
	float r0_ohm;
	bool calibrated;
};


class MqSensor {
 public:
	MqSensor(float pullup_ohm = 10000.0f, float vcc = 5.0f)
	    : pullup_ohm_(pullup_ohm), vcc_(vcc), r0_ohm_(0.0f), rs_ohm_(0.0f),
	      raw_adc_(0), voltage_v_(0.0f) {}

	void setCalibration(const MqCalibration& cal) {
		r0_ohm_ = cal.r0_ohm;
		calibrated_ = cal.calibrated;
	}

	bool isCalibrated() const { return calibrated_; }

	void updateFromVoltage(float voltage_v) {
		voltage_v_ = voltage_v;
		raw_adc_ = 0;  // ADC raw는 ADS1115에서만 의미
		rs_ohm_ = pullup_ohm_ * (vcc_ - voltage_v) / voltage_v;
	}

	float rsOhm() const { return rs_ohm_; }
	float rsR0Ratio() const {
		if (r0_ohm_ <= 0.0f) return 0.0f;
		return rs_ohm_ / r0_ohm_;
	}

 private:
	float pullup_ohm_;
	float vcc_;
	float r0_ohm_;
	float rs_ohm_;
	int raw_adc_;
	float voltage_v_;
	bool calibrated_ = false;
};

}  // namespace hp015::sensors
