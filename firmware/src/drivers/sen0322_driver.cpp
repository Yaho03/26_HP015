#include "drivers/sen0322_driver.h"

Sen0322Driver::Sen0322Driver(
    const uint8_t i2cAddress,
    const uint8_t collectNumber
)
    : i2cAddress_(i2cAddress),
      collectNumber_(collectNumber) {
}

bool Sen0322Driver::begin() {
    if (!sensor_.begin(i2cAddress_)) {
        Serial.println("[SEN0322] Initialization failed.");
        return false;
    }

    startMs_ = millis();

    Serial.println("[SEN0322] Initialization successful.");
    Serial.print("[SEN0322] I2C address: 0x");
    Serial.println(i2cAddress_, HEX);
    Serial.println("[SEN0322] Waiting 15 seconds before sampling.");

    return true;
}

bool Sen0322Driver::update() {
    newData_ = false;

    const unsigned long now = millis();

    if (isWaitingForResponse()) {
        return false;
    }

    if (now - lastSampleMs_ < SAMPLE_INTERVAL_MS) {
        return false;
    }

    lastSampleMs_ = now;

    /*
     * 변환식 근거 (이슈 #113 문제 1 — 검증):
     * 공식 DFRobot_OxygenSensor v1.0.2 (lib_deps 고정) 의 getOxygenData() 에
     * 위임한다. 라이브러리 소스의 변환식은
     *   key * (b0 + b1/10.0 + b2/100.0)   [%vol]
     * 이며 key 는 센서의 공장 교정 레지스터 값(value/1000, 비정상 시 20.9/120
     * 폴백) 이다. 예전 자체 구현은 b2 를 버리고 /1024*100 을 썼다 — DFRobot
     * 표준과 달라 본 이슈의 지적 대상이었고, 라이브러리 위임으로 제거됐다.
     * 교차 검증: 주변 공기에서 raw3 + raw4/10 + raw5/100 ≈ 20.7~20.9%vol
     * (DFRobot 포럼 실측 사례 및 데이터시트 정상 범위 일치).
     */
    const float oxygenPct =
        sensor_.getOxygenData(collectNumber_);

    /*
     * 주변 공기에서 보통 약 20~21%가 예상된다.
     * 비정상 범위는 읽기 오류로 처리한다.
     */
    if (oxygenPct <= 0.0F || oxygenPct > 30.0F) {
        data_.valid = false;

        Serial.print("[SEN0322] Invalid O2 value: ");
        Serial.println(oxygenPct);

        return false;
    }

    data_.o2Pct = oxygenPct;
    data_.valid = true;

    newData_ = true;
    return true;
}

bool Sen0322Driver::isWaitingForResponse() const {
    return millis() - startMs_ < STARTUP_WAIT_MS;
}

unsigned long Sen0322Driver::getRemainingWaitSeconds() const {
    const unsigned long elapsed = millis() - startMs_;

    if (elapsed >= STARTUP_WAIT_MS) {
        return 0;
    }

    return (STARTUP_WAIT_MS - elapsed + 999) / 1000;
}

bool Sen0322Driver::hasNewData() const {
    return newData_;
}

void Sen0322Driver::clearNewData() {
    newData_ = false;
}

const Sen0322Data& Sen0322Driver::getData() const {
    return data_;
}