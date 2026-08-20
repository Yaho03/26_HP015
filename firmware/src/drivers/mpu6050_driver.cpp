#include "drivers/mpu6050_driver.h"

#include <Wire.h>
#include <math.h>

namespace {

constexpr uint8_t REG_SMPLRT_DIV   = 0x19;
constexpr uint8_t REG_CONFIG       = 0x1A;
constexpr uint8_t REG_GYRO_CONFIG  = 0x1B;
constexpr uint8_t REG_ACCEL_CONFIG = 0x1C;
constexpr uint8_t REG_ACCEL_XOUT_H = 0x3B;
constexpr uint8_t REG_PWR_MGMT_1   = 0x6B;
constexpr uint8_t REG_WHO_AM_I     = 0x75;

}

Mpu6050Driver::Mpu6050Driver(
    const uint8_t i2cAddress
)
    : i2cAddress_(i2cAddress) {
}

bool Mpu6050Driver::writeRegister(
    const uint8_t reg,
    const uint8_t value
) {
    Wire.beginTransmission(i2cAddress_);
    Wire.write(reg);
    Wire.write(value);

    return Wire.endTransmission() == 0;
}

bool Mpu6050Driver::readRegisters(
    const uint8_t startReg,
    uint8_t* buffer,
    const size_t length
) {
    Wire.beginTransmission(i2cAddress_);
    Wire.write(startReg);

    if (Wire.endTransmission(false) != 0) {
        return false;
    }

    const size_t received =
        Wire.requestFrom(
            i2cAddress_,
            static_cast<uint8_t>(length)
        );

    if (received != length) {
        return false;
    }

    for (size_t i = 0; i < length; ++i) {
        buffer[i] = Wire.read();
    }

    return true;
}

uint8_t Mpu6050Driver::readRegister(
    const uint8_t reg
) {
    uint8_t value = 0;

    if (!readRegisters(
            reg,
            &value,
            1
        )) {
        return 0;
    }

    return value;
}

bool Mpu6050Driver::begin() {
    const uint8_t whoAmI =
        readRegister(REG_WHO_AM_I);

    Serial.print("[MPU6050] WHO_AM_I: 0x");

    if (whoAmI < 0x10) {
        Serial.print("0");
    }

    Serial.println(whoAmI, HEX);

    /*
     * 현재 보드는 WHO_AM_I = 0x72인
     * MPU6050 호환 칩이므로 0x68만 강제하지 않는다.
     *
     * I2C 응답이 정상이고 레지스터 읽기가 가능하면 진행한다.
     */
    if (whoAmI == 0x00 || whoAmI == 0xFF) {
        Serial.println("[MPU6050] Invalid chip ID.");
        return false;
    }

    // sleep 해제 + PLL clock
    if (!writeRegister(
            REG_PWR_MGMT_1,
            0x01
        )) {
        return false;
    }

    delay(100);

    // DLPF 설정
    if (!writeRegister(
            REG_CONFIG,
            0x03
        )) {
        return false;
    }

    // 1kHz / (1 + 9) = 100Hz
    if (!writeRegister(
            REG_SMPLRT_DIV,
            9
        )) {
        return false;
    }

    // gyro ±500 dps
    if (!writeRegister(
            REG_GYRO_CONFIG,
            0x08
        )) {
        return false;
    }

    // accel ±4g
    if (!writeRegister(
            REG_ACCEL_CONFIG,
            0x08
        )) {
        return false;
    }

    Serial.println("[MPU6050] Initialization successful.");
    Serial.println("[MPU6050] Accel range: +/-4g");
    Serial.println("[MPU6050] Gyro range: +/-500 dps");
    Serial.println("[MPU6050] Sampling: 100Hz");

    return true;
}

bool Mpu6050Driver::update() {
    newData_ = false;

    const unsigned long now = millis();

    if (now - lastSampleMs_ < SAMPLE_INTERVAL_MS) {
        return false;
    }

    lastSampleMs_ = now;

    uint8_t raw[14];

    if (!readRegisters(
            REG_ACCEL_XOUT_H,
            raw,
            sizeof(raw)
        )) {
        data_.valid = false;
        return false;
    }

    const int16_t rawAx =
        static_cast<int16_t>(
            (raw[0] << 8) | raw[1]
        );

    const int16_t rawAy =
        static_cast<int16_t>(
            (raw[2] << 8) | raw[3]
        );

    const int16_t rawAz =
        static_cast<int16_t>(
            (raw[4] << 8) | raw[5]
        );

    const int16_t rawGx =
        static_cast<int16_t>(
            (raw[8] << 8) | raw[9]
        );

    const int16_t rawGy =
        static_cast<int16_t>(
            (raw[10] << 8) | raw[11]
        );

    const int16_t rawGz =
        static_cast<int16_t>(
            (raw[12] << 8) | raw[13]
        );

    data_.accelXG = rawAx / ACCEL_SCALE;
    data_.accelYG = rawAy / ACCEL_SCALE;
    data_.accelZG = rawAz / ACCEL_SCALE;

    data_.gyroXDps = rawGx / GYRO_SCALE;
    data_.gyroYDps = rawGy / GYRO_SCALE;
    data_.gyroZDps = rawGz / GYRO_SCALE;

    data_.accelMagnitudeG =
        sqrt(
            data_.accelXG * data_.accelXG
            + data_.accelYG * data_.accelYG
            + data_.accelZG * data_.accelZG
        );

    data_.valid = true;
    newData_ = true;

    return true;
}

bool Mpu6050Driver::hasNewData() const {
    return newData_;
}

void Mpu6050Driver::clearNewData() {
    newData_ = false;
}

const Mpu6050Data&
Mpu6050Driver::getData() const {
    return data_;
}