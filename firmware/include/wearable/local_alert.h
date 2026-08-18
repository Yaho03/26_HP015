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
class LocalAlert {
 public:
	explicit LocalAlert(VibrationMotor& motor) : motor_(motor), last_local_alert_(false) {}

	bool evaluate(float o2_pct) {
		const bool danger = (o2_pct < O2_LOW_CRITICAL_PCT) || (o2_pct > O2_HIGH_CRITICAL_PCT);
		if (danger) {
			motor_.continuous();
		} else {
			motor_.stop();
		}
		last_local_alert_ = danger;
		return danger;
	}

	bool isActive() const { return last_local_alert_; }

	static constexpr float O2_LOW_CRITICAL_PCT  = 16.0f;
	static constexpr float O2_HIGH_CRITICAL_PCT = 28.0f;

 private:
	VibrationMotor& motor_;
	bool last_local_alert_;
};

}  // namespace hp015::wearable
