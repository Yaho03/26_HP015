#pragma once

#include <Arduino.h>

namespace hp015::sensors {

enum class CalibrationState {
    NOT_STARTED,
    IN_PROGRESS,
    DONE,
    ERROR_,
};

// MQ 시리즈 가스 센서 R0 교정 (이슈 #48).
//
// MQ 센서는 깨끗한 공기(clean air) 에서 안정화 후 Rs 를 측정해 R0 를 계산한다.
// R0 = Rs / Ro_Rs_Ratio (청정 공기에서의 Rs/R0 비, 센서별 데이터시트 값).
//
// 교정 절차 (03_HARDWARE_DESIGN.md 교정 섹션):
//   1. 센서를 청정 공기 환경에 노출 (실외 또는 환기된 곳)
//   2. Warm-up: 최소 24시간 (MQ-7), 48시간 (MQ-136) 예열
//   3. 안정화 대기: Rs 변동 ±5% 이내를 5분간 유지
//   4. R0 계산: R0 = Rs_stable / clean_air_ratio
//   5. 교정 상태 DONE 으로 전환, EEPROM 저장 (별도 구현)
class MqCalibrator {
 public:
	MqCalibrator(float clean_air_ratio, unsigned long warmup_ms = 86400000UL,
	             unsigned long stability_window_ms = 300000UL, float stability_threshold_pct = 5.0f)
	    : clean_air_ratio_(clean_air_ratio),
	      warmup_ms_(warmup_ms),
	      stability_window_ms_(stability_window_ms),
	      stability_threshold_pct_(stability_threshold_pct),
	      state_(CalibrationState::NOT_STARTED),
	      start_ms_(0),
	      stable_since_ms_(0),
	      r0_ohm_(0.0f),
	      avg_ohm_(0.0f),
	      spread_pct_(0.0f),
	      samples_count_(0),
	      samples_sum_(0.0f),
	      samples_min_(1e9f),
	      samples_max_(0.0f),
	      sample_index_(0),
	      sample_window_count_(0) {}

	void begin() {
		start_ms_ = millis();
		stable_since_ms_ = 0;
		state_ = CalibrationState::IN_PROGRESS;
		samples_count_ = 0;
		samples_sum_ = 0.0f;
		samples_min_ = 1e9f;
		samples_max_ = 0.0f;
		avg_ohm_ = 0.0f;
		spread_pct_ = 0.0f;
		sample_index_ = 0;
		sample_window_count_ = 0;
	}

	CalibrationState state() const { return state_; }

	float r0Ohm() const { return r0_ohm_; }
	float averageOhm() const { return avg_ohm_; }
	float spreadPct() const { return spread_pct_; }
	bool hasWindow() const { return sample_window_count_ == SAMPLE_WINDOW_SIZE; }
	bool isStableNow() const {
		return hasWindow() && spread_pct_ <= stability_threshold_pct_;
	}

	float r0CandidateOhm() const {
		if (clean_air_ratio_ <= 0.0f || avg_ohm_ <= 0.0f) return 0.0f;
		return avg_ohm_ / clean_air_ratio_;
	}

	CalibrationState update(float rs_ohm) {
		if (state_ != CalibrationState::IN_PROGRESS) return state_;
		if (!isfinite(rs_ohm) || rs_ohm <= 0.0f) return state_;

		const unsigned long now_ms = millis();
		unsigned long elapsed = now_ms - start_ms_;
		if (elapsed < warmup_ms_) {
			return state_;
		}

		samples_[sample_index_] = rs_ohm;
		sample_index_ = (sample_index_ + 1) % SAMPLE_WINDOW_SIZE;
		if (sample_window_count_ < SAMPLE_WINDOW_SIZE) sample_window_count_++;

		samples_sum_ = 0.0f;
		samples_min_ = 1e9f;
		samples_max_ = 0.0f;

		for (uint8_t i = 0; i < sample_window_count_; ++i) {
			const float sample = samples_[i];
			samples_sum_ += sample;
			if (sample < samples_min_) samples_min_ = sample;
			if (sample > samples_max_) samples_max_ = sample;
		}

		samples_count_++;
		avg_ohm_ = samples_sum_ / sample_window_count_;
		spread_pct_ = ((samples_max_ - samples_min_) / avg_ohm_) * 100.0f;

		if (!hasWindow()) return state_;

		if (spread_pct_ <= stability_threshold_pct_) {
			if (stable_since_ms_ == 0) stable_since_ms_ = now_ms;
		} else {
			stable_since_ms_ = 0;
		}

		if (
			stable_since_ms_ != 0
			&& now_ms - stable_since_ms_ >= stability_window_ms_
		) {
			r0_ohm_ = r0CandidateOhm();
			state_ = CalibrationState::DONE;
		}

		return state_;
	}

 private:
	static constexpr uint8_t SAMPLE_WINDOW_SIZE = 60;

	float clean_air_ratio_;
	unsigned long warmup_ms_;
	unsigned long stability_window_ms_;
	float stability_threshold_pct_;
	CalibrationState state_;
	unsigned long start_ms_;
	unsigned long stable_since_ms_;
	float r0_ohm_;
	float avg_ohm_;
	float spread_pct_;
	unsigned long samples_count_;
	float samples_sum_;
	float samples_min_;
	float samples_max_;
	float samples_[SAMPLE_WINDOW_SIZE] = {};
	uint8_t sample_index_;
	uint8_t sample_window_count_;
};


// BME680 burn-in 카운터 (이슈 #48).
// BME680 BSEC 라이브러리는 burn-in (최소 5분 권장, 정확도 향상을 위해 1시간 권장)
// 후에 iaq_accuracy 가 0→1→2 로 상승한다.
class Bme680BurnIn {
 public:
	explicit Bme680BurnIn(unsigned long target_ms = 3600000UL)
	    : target_ms_(target_ms), start_ms_(0), running_(false), iaq_accuracy_(0) {}

	void begin() {
		start_ms_ = millis();
		running_ = true;
	}

	bool isComplete() const {
		if (!running_) return false;
		return (millis() - start_ms_) >= target_ms_;
	}

	unsigned long elapsedMs() const {
		if (!running_) return 0;
		return millis() - start_ms_;
	}

	unsigned long remainingMs() const {
		if (!running_) return target_ms_;
		unsigned long rem = target_ms_ - (millis() - start_ms_);
		return rem > target_ms_ ? 0 : rem;
	}

	void setIaqAccuracy(int accuracy) { iaq_accuracy_ = accuracy; }
	int iaqAccuracy() const { return iaq_accuracy_; }
	bool isReady() const { return iaq_accuracy_ >= 2; }

 private:
	unsigned long target_ms_;
	unsigned long start_ms_;
	bool running_;
	int iaq_accuracy_;
};

}  // namespace hp015::sensors
