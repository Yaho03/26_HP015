#pragma once

#include <Arduino.h>
#include <DFRobot_OxygenSensor.h>

struct Sen0322Data {
    float o2Pct = 0.0F;
    bool valid = false;
};

class Sen0322Driver {
public:
    Sen0322Driver(
        uint8_t i2cAddress = ADDRESS_3,
        uint8_t collectNumber = 10
    );

    bool begin();
    bool update();

    bool isWaitingForResponse() const;
    unsigned long getRemainingWaitSeconds() const;

    bool hasNewData() const;
    void clearNewData();

    const Sen0322Data& getData() const;

private:
    uint8_t i2cAddress_;
    uint8_t collectNumber_;

    DFRobot_OxygenSensor sensor_;
    Sen0322Data data_;

    unsigned long startMs_ = 0;
    unsigned long lastSampleMs_ = 0;

    bool newData_ = false;

    static constexpr unsigned long STARTUP_WAIT_MS = 15000;
    static constexpr unsigned long SAMPLE_INTERVAL_MS = 5000;
};