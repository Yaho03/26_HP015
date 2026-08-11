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
		uint8_t cmd[9] = {0xFF, 0x01, 0x86, 0x00, 0x00, 0x00, 0x00, 0x00, 0x79};
		uint8_t resp[9] = {0};

		serial_->write(cmd, 9);
		serial_->flush();

		unsigned long start = millis();
		while (serial_->available() < 9 && millis() - start < 1000) {
			delay(10);
		}
		if (serial_->available() < 9) {
			return last_ppm_;
		}
		serial_->readBytes(resp, 9);

		if (resp[0] != 0xFF || resp[1] != 0x86) {
			return last_ppm_;
		}
		uint8_t checksum = 0;
		for (int i = 1; i < 8; i++) {
			checksum += resp[i];
		}
		checksum = 0xFF - checksum;
		checksum += 1;
		if (resp[8] != checksum) {
			return last_ppm_;
		}

		int ppm = (resp[2] << 8) | resp[3];
		last_ppm_ = ppm;
		last_read_ms_ = millis();
		return ppm;
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
