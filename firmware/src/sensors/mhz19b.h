#pragma once

#include <Arduino.h>

namespace hp015::sensors {

class Mhz19b {
 public:
	static constexpr uint8_t DEFAULT_RX_PIN = 16;
	static constexpr uint8_t DEFAULT_TX_PIN = 17;

	explicit Mhz19b(uint8_t rx_pin = DEFAULT_RX_PIN, uint8_t tx_pin = DEFAULT_TX_PIN,
	                HardwareSerial* serial = &Serial2)
	    : rx_pin_(rx_pin), tx_pin_(tx_pin), serial_(serial), last_ppm_(400), last_read_ms_(0) {}

	void begin() {
		serial_->begin(9600, SERIAL_8N1, rx_pin_, tx_pin_);
	}

	int readCo2Ppm() {
		// TODO(#39): 9-byte 응답 파싱 (0xFF 시작, byte 2/3 = high/low ppm, byte 8 = checksum).
		last_read_ms_ = millis();
		return last_ppm_;
	}

	void setSimulatedValue(int ppm) { last_ppm_ = ppm; }

	bool isFresh(unsigned long max_age_ms = 5000) const {
		return (millis() - last_read_ms_) < max_age_ms;
	}

 private:
	uint8_t rx_pin_;
	uint8_t tx_pin_;
	HardwareSerial* serial_;
	int last_ppm_;
	unsigned long last_read_ms_;
};

}  // namespace hp015::sensors
