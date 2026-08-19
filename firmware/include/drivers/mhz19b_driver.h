#pragma once

// MH-Z19B 측정 범위 상한(ppm). 0~2000 / 0~5000 / 0~10000 변종이 있다.
// 구매 모델에 맞춰 platformio.ini 에서 -D MHZ19B_RANGE_PPM=... 으로 지정한다.
#ifndef MHZ19B_RANGE_PPM
#define MHZ19B_RANGE_PPM 5000
#endif


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