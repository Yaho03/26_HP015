#pragma once

#include "vibration_motor.h"

namespace hp015::wearable {

// 웨어러블 로컬 O₂ 폴백 경보 (이슈 #86, safety-critical).
//
// 배경: 백엔드/MQTT 브로커 장애 시에도 작업자 안전 경보가 동작해야 한다.
//       SEN0322 O₂ 센서 값을 읽어 펌웨어 내에서 즉시 임계값 검사 후
//       진동 모터를 자율 구동한다. (06_ALERT_RULES 섹션 12)
//
// 임계값 (06_ALERT_RULES 4.2, 백엔드 thresholds 테이블 L3 과 동일):
//   O₂ < 16.0%  → 연속 진동
//   O₂ > 28.0%  → 연속 진동
//   정상 회귀 시 진동 정지
//
// 로컬 임계값은 펌웨어에 하드코딩한다 (백엔드 장애 시 설정 조회 불가하므로).
//
// ── 읽기 실패는 "정상"이 아니다 (이슈 #113 문제 2) ───────────────────────
// 예전 구현은 유효한 값만 받아 판정했고, 센서가 죽으면 아무 판단도 하지 않아
// 진동이 멈춘 채로 있었다. 작업자에게는 "산소 정상"과 구별되지 않는다.
// 밀폐공간에서 산소결핍은 최우선 위험이고 무증상으로 의식을 잃는다 —
// 센서가 고장 났다는 사실 자체가 위험 신호여야 한다.
//
// 다만 두 가지를 구분한다.
//   * 예열 중(warming up): 아직 판정할 수 없다. 진동하지 않는다. 기동 직후
//     15초를 위험으로 보면 매번 켤 때마다 오경보가 난다.
//   * 실패 지속: STALE_READING_MS 동안 유효한 값이 한 번도 없으면 위험이다.
//     한 번의 I2C 흔들림으로 울리지 않게 유예를 두되, 센서를 뽑으면 반드시 운다.
class LocalAlert {
 public:
	explicit LocalAlert(VibrationMotor& motor)
		: motor_(motor), last_local_alert_(false), last_valid_ms_(0), started_(false), degraded_(false) {}

	// 판정 시작 시각을 잡는다. 이걸 부르지 않으면 last_valid_ms_ 가 0 이라
	// millis() 가 STALE_READING_MS 를 넘는 순간 곧바로 위험으로 뒤집힌다.
	void begin(unsigned long now_ms) {
		last_valid_ms_ = now_ms;
		started_ = true;
	}

	// reading_valid: 이번에 유효한 값을 얻었는가 (Sen0322Data::valid).
	// warming_up:    센서 예열 대기 중인가 (Sen0322Driver::isWaitingForResponse).
	//
	// 유효한 값이 없어도 매 루프 호출해야 한다. 실패 지속을 시간으로 재기 때문이다.
	bool evaluate(float o2_pct, bool reading_valid, bool warming_up, unsigned long now_ms) {
		if (!started_) {
			begin(now_ms);
		}

		if (reading_valid) {
			last_valid_ms_ = now_ms;
			degraded_ = false;
			return apply((o2_pct < O2_LOW_CRITICAL_PCT) || (o2_pct > O2_HIGH_CRITICAL_PCT));
		}

		if (warming_up) {
			// 예열 중에는 판정하지 않는다. 값이 없는 것이지 나쁜 것이 아니다.
			last_valid_ms_ = now_ms;
			degraded_ = false;
			return apply(false);
		}

		if (now_ms - last_valid_ms_ >= STALE_READING_MS) {
			// 센서가 죽었다. 산소 상태를 알 수 없다는 것을 작업자에게 알린다.
			degraded_ = true;
			return apply(true);
		}

		// 짧은 결측. 직전 판정을 유지한다 — 여기서 진동을 끄면 실제 위험 상황에서
		// 읽기 하나가 빠질 때마다 경보가 끊긴다.
		return last_local_alert_;
	}

	bool isActive() const { return last_local_alert_; }

	// 센서 실패 때문에 울리고 있는가. 상태 보고가 "산소 낮음"과 "센서 죽음"을
	// 구분해 올릴 수 있어야 한다 — 조치가 다르다.
	bool isDegraded() const { return degraded_; }

	static constexpr float O2_LOW_CRITICAL_PCT  = 16.0f;
	static constexpr float O2_HIGH_CRITICAL_PCT = 28.0f;

	// 유효한 값 없이 이 시간이 지나면 센서 고장으로 본다.
	// 드라이버 샘플 주기가 5초이므로 연속 3회 실패에 해당한다.
	static constexpr unsigned long STALE_READING_MS = 15000;

 private:
	bool apply(bool danger) {
		if (danger) {
			motor_.continuous();
		} else {
			motor_.stop();
		}
		last_local_alert_ = danger;
		return danger;
	}

	VibrationMotor& motor_;
	bool last_local_alert_;
	unsigned long last_valid_ms_;
	bool started_;
	bool degraded_;
};

}  // namespace hp015::wearable
