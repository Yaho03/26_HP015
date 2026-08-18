#pragma once

#include <Arduino.h>

struct Mhz19bData {
    int co2Ppm = 0;
    bool valid = false;
};

class Mhz19bDriver {
public:
    Mhz19bDriver(
        HardwareSerial& serialPort,
        int8_t rxPin,
        int8_t txPin
    );

    void begin();

    // loop()에서 계속 호출
    bool update();

    bool isWarmingUp() const;
    unsigned long getRemainingWarmupSeconds() const;

    bool hasNewData() const;
    void clearNewData();

    const Mhz19bData& getData() const;

private:
    static uint8_t calculateChecksum(const uint8_t* packet);
    bool readCo2(int& co2Ppm);

    HardwareSerial& serialPort_;

    int8_t rxPin_;
    int8_t txPin_;

    unsigned long startMs_ = 0;
    unsigned long lastSampleMs_ = 0;
    unsigned long lastWarmupPrintMs_ = 0;

    bool newData_ = false;
    Mhz19bData data_;

    static constexpr unsigned long WARMUP_MS = 60000;
    static constexpr unsigned long SAMPLE_INTERVAL_MS = 1000;
    static constexpr unsigned long RESPONSE_TIMEOUT_MS = 500;
};