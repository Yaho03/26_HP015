#include "drivers/ads1115_mq_driver.h"

Ads1115MqDriver::Ads1115MqDriver(
    const uint8_t i2cAddress,
    const float circuitVoltageV,
    const float loadResistanceOhm
)
    : i2cAddress_(i2cAddress),
      circuitVoltageV_(circuitVoltageV),
      loadResistanceOhm_(loadResistanceOhm) {
}

bool Ads1115MqDriver::begin() {
    if (!ads_.begin(i2cAddress_)) {
        Serial.println("[ADS1115] Initialization failed.");
        return false;
    }

    /*
     * GAIN_ONE:
     * 측정 범위 약 ±4.096 V
     * ADS1115 입력 전압이 이 범위를 넘지 않도록
     * 실제 분압 회로를 반드시 확인해야 한다.
     */
    ads_.setGain(GAIN_ONE);

    data_.mq7.type = MqSensorType::MQ7;
    data_.mq7.channel = 0;

    data_.mq136.type = MqSensorType::MQ136;
    data_.mq136.channel = 1;

    data_.mq2.type = MqSensorType::MQ2;
    data_.mq2.channel = 2;

    data_.spare.type = MqSensorType::SPARE;
    data_.spare.channel = 3;

    Serial.println("[ADS1115] Initialization successful.");
    Serial.println("[ADS1115] I2C address: 0x48");

    return true;
}

bool Ads1115MqDriver::update() {
    newData_ = false;

    const unsigned long now = millis();

    if (now - lastSampleMs_ < SAMPLE_INTERVAL_MS) {
        return false;
    }

    lastSampleMs_ = now;

    data_.mq2 = readChannel(
    0,
    MqSensorType::MQ2,
    mq2R0Ohm_
    );

    data_.mq7 = readChannel(
    1,
    MqSensorType::MQ7,
    mq7R0Ohm_
    );

    data_.mq136 = readChannel(
    2,
    MqSensorType::MQ136,
    mq136R0Ohm_
    );

    data_.spare = readChannel(
        3,
        MqSensorType::SPARE,
        0.0F
    );

    data_.valid =
        data_.mq7.valid
        && data_.mq136.valid
        && data_.mq2.valid
        && data_.spare.valid;

    newData_ = true;
    return true;
}

MqChannelData Ads1115MqDriver::readChannel(
    const uint8_t channel,
    const MqSensorType type,
    const float r0Ohm
) {
    MqChannelData result;

    result.type = type;
    result.channel = channel;
    result.r0Ohm = r0Ohm;

    result.rawAdc = ads_.readADC_SingleEnded(channel);

    /*
     * Adafruit 라이브러리가 현재 gain 설정에 맞는
     * 실제 전압값을 반환한다.
     */
    result.voltageV = ads_.computeVolts(result.rawAdc);

    if (
        result.voltageV <= 0.0F
        || result.voltageV >= circuitVoltageV_
    ) {
        result.valid = false;
        return result;
    }

    result.rsOhm =
        calculateSensorResistance(result.voltageV);

    /*
     * 교정 전에는 R0가 0이므로
     * Rs/R0를 유효값으로 취급하지 않는다.
     */
    if (result.r0Ohm > 0.0F) {
        result.rsR0Ratio =
            result.rsOhm / result.r0Ohm;
    } else {
        result.rsR0Ratio = 0.0F;
    }

    result.valid = true;
    return result;
}

float Ads1115MqDriver::calculateSensorResistance(
    const float outputVoltageV
) const {
    /*
     * 일반적인 MQ 분압 회로:
     *
     * Vc ─ Rs ─┬─ Vout
     *           |
     *           RL
     *           |
     *          GND
     *
     * Rs = RL × (Vc - Vout) / Vout
     *
     * 실제 회로가 이 구조인지 문서에서 확인해야 한다.
     */
    return loadResistanceOhm_
        * (circuitVoltageV_ - outputVoltageV)
        / outputVoltageV;
}

bool Ads1115MqDriver::hasNewData() const {
    return newData_;
}

void Ads1115MqDriver::clearNewData() {
    newData_ = false;
}

const Ads1115MqData& Ads1115MqDriver::getData() const {
    return data_;
}

void Ads1115MqDriver::setR0Values(
    const float mq7R0Ohm,
    const float mq136R0Ohm,
    const float mq2R0Ohm
) {
    mq7R0Ohm_ = mq7R0Ohm;
    mq136R0Ohm_ = mq136R0Ohm;
    mq2R0Ohm_ = mq2R0Ohm;
}