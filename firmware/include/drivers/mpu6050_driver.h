#pragma once

#include <Arduino.h>

struct Mpu6050Data {
    float accelXG = 0.0F;
    float accelYG = 0.0F;
    float accelZG = 0.0F;

    float gyroXDps = 0.0F;
    float gyroYDps = 0.0F;
    float gyroZDps = 0.0F;

    float accelMagnitudeG = 0.0F;

    bool valid = false;
};

class Mpu6050Driver {
public:
    explicit Mpu6050Driver(
        uint8_t i2cAddress = 0x68
    );

    bool begin();
    bool update();

    bool hasNewData() const;
    void clearNewData();

    const Mpu6050Data& getData() const;

private:
    bool writeRegister(
        uint8_t reg,
        uint8_t value
    );

    bool readRegisters(
        uint8_t startReg,
        uint8_t* buffer,
        size_t length
    );

    uint8_t readRegister(
        uint8_t reg
    );

    uint8_t i2cAddress_;

    Mpu6050Data data_;

    unsigned long lastSampleMs_ = 0;
    bool newData_ = false;

    static constexpr unsigned long SAMPLE_INTERVAL_MS = 10;

    static constexpr float ACCEL_SCALE = 8192.0F;
    static constexpr float GYRO_SCALE = 65.5F;
};