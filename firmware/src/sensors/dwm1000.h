#pragma once

#include <Arduino.h>
#include <SPI.h>

namespace hp015::sensors {

// DWM1000 UWB 모듈 드라이버 인터페이스 (이슈 #68).
// SPI 통신으로 거리 측정 (DS-TWR, Double-Sided Two-Way Ranging).
// 4개 앵커와 태그 간 거리를 측정 → #69 Least Squares 로 2D 위치 추정.
//
// 본 헤더는 인터페이스만 제공한다 — 실제 DW1000 레지스터/프레임 프로토콜은
// #68 에서 완성한다. dwm1000-arduino 라이브러리 또는 직접 SPI 구현 필요.
class Dwm1000 {
 public:
	static constexpr uint8_t DEFAULT_CS_PIN   = 15;
	static constexpr uint8_t DEFAULT_RST_PIN  = 4;
	static constexpr uint8_t DEFAULT_IRQ_PIN  = 5;
	static constexpr float   SPEED_OF_LIGHT_MPS = 299702547.0f;

	Dwm1000(uint8_t cs_pin = DEFAULT_CS_PIN, uint8_t rst_pin = DEFAULT_RST_PIN,
	        uint8_t irq_pin = DEFAULT_IRQ_PIN, SPIClass* spi = &SPI)
	    : cs_pin_(cs_pin), rst_pin_(rst_pin), irq_pin_(irq_pin), spi_(spi),
	      last_distance_m_(0.0f), last_read_ms_(0) {}

	bool begin() {
		pinMode(cs_pin_, OUTPUT);
		pinMode(rst_pin_, OUTPUT);
		pinMode(irq_pin_, INPUT);
		digitalWrite(cs_pin_, HIGH);
		// TODO(#68): DW1000 init, SPI rate 설정, antenna delay calibration.
		return true;
	}

	float measureDistanceMeters(uint16_t anchor_id) {
		// TODO(#68): DS-TWR 프로토콜 (POLL → RESP → FINAL), timestamp → ToF → distance.
		// distance = (T_round1 - T_reply1) * (T_round2 - T_reply2) /
		//            (4 * (T_round1 + T_round2 - T_reply1 - T_reply2)) * c
		(void)anchor_id;
		last_read_ms_ = millis();
		return last_distance_m_;
	}

	float lastDistanceMeters() const { return last_distance_m_; }

	void setSimulatedDistance(float meters) {
		last_distance_m_ = meters;
		last_read_ms_ = millis();
	}

	bool isFresh(unsigned long max_age_ms = 1000) const {
		return (millis() - last_read_ms_) < max_age_ms;
	}

 private:
	uint8_t cs_pin_;
	uint8_t rst_pin_;
	uint8_t irq_pin_;
	SPIClass* spi_;
	float last_distance_m_;
	unsigned long last_read_ms_;
};

}  // namespace hp015::sensors
