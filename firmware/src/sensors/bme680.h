#pragma once

#include <Arduino.h>
#include <Wire.h>

namespace hp015::sensors {

class Bme680 {
 public:
	static constexpr uint8_t DEFAULT_I2C_ADDRESS = 0x77;

	explicit Bme680(uint8_t address = DEFAULT_I2C_ADDRESS, TwoWire* wire = &Wire)
	    : address_(address), wire_(wire),
	      temperature_c_(25.0f), humidity_pct_(50.0f), pressure_hpa_(1013.0f),
	      gas_resistance_ohm_(10000.0f), iaq_index_(50), iaq_accuracy_(0),
	      last_read_ms_(0) {}

	bool begin() {
		wire_->beginTransmission(address_);
		return wire_->endTransmission() == 0;
	}

	void readAll() {
		// TODO(#40): BSEC 라이브러리 연동. iaq_accuracy >= 2 일 때만 IAQ 값 사용.
		last_read_ms_ = millis();
	}

	float temperatureC() const { return temperature_c_; }
	float humidityPct() const { return humidity_pct_; }
	float pressureHpa() const { return pressure_hpa_; }
	float gasResistanceOhm() const { return gas_resistance_ohm_; }
	int iaqIndex() const { return iaq_index_; }
	int iaqAccuracy() const { return iaq_accuracy_; }

	void setSimulated(float temp, float hum, float pres, float gas, int iaq, int acc) {
		temperature_c_ = temp;
		humidity_pct_ = hum;
		pressure_hpa_ = pres;
		gas_resistance_ohm_ = gas;
		iaq_index_ = iaq;
		iaq_accuracy_ = acc;
		last_read_ms_ = millis();
	}

	bool isFresh(unsigned long max_age_ms = 5000) const {
		return (millis() - last_read_ms_) < max_age_ms;
	}

 private:
	uint8_t address_;
	TwoWire* wire_;
	float temperature_c_;
	float humidity_pct_;
	float pressure_hpa_;
	float gas_resistance_ohm_;
	int iaq_index_;
	int iaq_accuracy_;
	unsigned long last_read_ms_;
};

}  // namespace hp015::sensors
