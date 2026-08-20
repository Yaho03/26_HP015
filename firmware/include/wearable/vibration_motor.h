#pragma once

#include <Arduino.h>

namespace hp015::wearable {

// 진동 모터 NPN low-side switch (03_HARDWARE_DESIGN 섹션 11).
//   +5V ─ 모터 ─ Collector (S8050)
//   Base ─ 1kΩ ─ GPIO25
//   Emitter ─ GND
//   1N4007 다이오드: Cathode=+5V, Anode=Collector (역기전력 보호)
class VibrationMotor {
 public:
	explicit VibrationMotor(uint8_t pin = 25) : pin_(pin), active_(false) {}

	void begin() { pinMode(pin_, OUTPUT); digitalWrite(pin_, LOW); }

	void continuous() {
		digitalWrite(pin_, HIGH);
		active_ = true;
	}

	void stop() {
		digitalWrite(pin_, LOW);
		active_ = false;
	}

	bool isActive() const { return active_; }

 private:
	uint8_t pin_;
	bool active_;
};

}  // namespace hp015::wearable
