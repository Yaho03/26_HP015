#pragma once

#include <Arduino.h>
#include "vibration_motor.h"

namespace hp015::wearable {

// 06_ALERT_RULES.md 섹션 11 진동 패턴 구현 (이슈 #47, #86).
//   Level 1 (주의): 0.5초 진동 × 2회
//   Level 2 (경고): 1초 진동 × 3회, 2초 대기, 반복
//   Level 3 (위험): 연속 진동 (중단 없이)
class VibrationPatterns {
 public:
	enum class Phase { IDLE, ON, OFF };

	explicit VibrationPatterns(VibrationMotor& motor, unsigned long tick_ms = 50)
	    : motor_(motor), tick_ms_(tick_ms),
	      level_(0), phase_(Phase::IDLE), phase_start_ms_(0),
	      burst_count_(0), burst_target_(0), on_ms_(0), off_ms_(0), cycle_off_ms_(0) {}

	void playLevel1() {
		startPattern(/*target*/ 2, /*on*/ 500, /*off*/ 500, /*cycle_off*/ 0, /*level*/ 1);
	}

	void playLevel2() {
		startPattern(/*target*/ 3, /*on*/ 1000, /*off*/ 200, /*cycle_off*/ 2000, /*level*/ 2);
	}

	void playLevel3() {
		motor_.continuous();
		level_ = 3;
		phase_ = Phase::ON;
		phase_start_ms_ = millis();
	}

	void stop() {
		motor_.stop();
		level_ = 0;
		phase_ = Phase::IDLE;
		burst_count_ = 0;
	}

	int currentLevel() const { return level_; }

	void tick() {
		if (level_ == 0 || phase_ == Phase::IDLE) return;
		if (level_ == 3) return;

		unsigned long now = millis();
		if (now - phase_start_ms_ < tick_ms_) return;
		unsigned long elapsed = now - phase_start_ms_;

		if (phase_ == Phase::ON && elapsed >= on_ms_) {
			motor_.stop();
			phase_ = Phase::OFF;
			phase_start_ms_ = now;
		} else if (phase_ == Phase::OFF && elapsed >= off_ms_) {
			burst_count_++;
			if (burst_count_ >= burst_target_) {
				if (cycle_off_ms_ > 0) {
					phase_ = Phase::IDLE;
					phase_start_ms_ = now;
					burst_count_ = 0;
					schedule_resume_ms_ = now + cycle_off_ms_;
				} else {
					playLevel1();
				}
			} else {
				motor_.continuous();
				phase_ = Phase::ON;
				phase_start_ms_ = now;
			}
		} else if (phase_ == Phase::IDLE && now >= schedule_resume_ms_) {
			if (level_ == 1) playLevel1();
			else if (level_ == 2) playLevel2();
		}
	}

 private:
	VibrationMotor& motor_;
	unsigned long tick_ms_;
	int level_;
	Phase phase_;
	unsigned long phase_start_ms_;
	int burst_count_;
	int burst_target_;
	unsigned long on_ms_;
	unsigned long off_ms_;
	unsigned long cycle_off_ms_;
	unsigned long schedule_resume_ms_ = 0;

	void startPattern(int target, unsigned long on_ms, unsigned long off_ms,
	                  unsigned long cycle_off_ms, int level) {
		burst_target_ = target;
		on_ms_ = on_ms;
		off_ms_ = off_ms;
		cycle_off_ms_ = cycle_off_ms;
		level_ = level;
		burst_count_ = 0;
		motor_.continuous();
		phase_ = Phase::ON;
		phase_start_ms_ = millis();
	}
};

}  // namespace hp015::wearable
