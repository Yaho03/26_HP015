#pragma once

#include <Arduino.h>
#include <Adafruit_ADS1X15.h>

enum class MqSensorType : uint8_t {
    MQ7,
    MQ136,
    MQ2,
    SPARE
};

struct MqChannelData {
    MqSensorType type = MqSensorType::SPARE;
    uint8_t channel = 0;

    int16_t rawAdc = 0;
    float voltageV = 0.0F;

    float rsOhm = 0.0F;
    float r0Ohm = 0.0F;
    float rsR0Ratio = 0.0F;

    bool valid = false;
};

struct Ads1115MqData {
    MqChannelData mq7;
    MqChannelData mq136;
    MqChannelData mq2;
    MqChannelData spare;

    bool valid = false;
};

class Ads1115MqDriver {
public:
    Ads1115MqDriver(
        uint8_t i2cAddress = 0x48,
        float circuitVoltageV = 5.0F,
        float loadResistanceOhm = 10000.0F
    );

    bool begin();
    bool update();

    bool hasNewData() const;
    void clearNewData();

    const Ads1115MqData& getData() const;

    void setR0Values(
        float mq7R0Ohm,
        float mq136R0Ohm,
        float mq2R0Ohm
    );

private:
    MqChannelData readChannel(
        uint8_t channel,
        MqSensorType type,
        float r0Ohm
    );

    float calculateSensorResistance(float outputVoltageV) const;

    uint8_t i2cAddress_;
    float circuitVoltageV_;
    float loadResistanceOhm_;

    float mq7R0Ohm_ = 0.0F;
    float mq136R0Ohm_ = 0.0F;
    float mq2R0Ohm_ = 0.0F;

    Adafruit_ADS1115 ads_;
    Ads1115MqData data_;

    unsigned long lastSampleMs_ = 0;
    bool newData_ = false;

    static constexpr unsigned long SAMPLE_INTERVAL_MS = 1000;
};