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
    bool readFrame(int& co2Ppm);

    HardwareSerial& serialPort_;

    int8_t rxPin_;
    int8_t txPin_;

    unsigned long startMs_ = 0;
    unsigned long lastSampleMs_ = 0;
    unsigned long lastWarmupPrintMs_ = 0;

    bool newData_ = false;
    Mhz19bData data_;

    /*
     * 예열 대기. 이것은 '보드 부팅 후 경과'이지 '센서 전원 인가 후 경과'가
     * 아니다. 센서 전원이 계속 들어와 있는데 보드만 재플래시하면 매번 다시
     * 60초를 버린다 (2026-08-19 실물 작업에서 반복 낭비).
     *
     * 보드는 센서가 언제부터 전원을 받았는지 알 수 없다 — MQ 교정에서 이미
     * 같은 결론을 내리고 MQ_CALIBRATION_WARMUP_MS 를 0 으로 두었다.
     * 현장 콜드스타트 보호를 위해 기본값은 60초로 두되, 벤치 작업 시에는
     * platformio.ini 에서 -D MHZ19B_WARMUP_MS=0 으로 끌 수 있게 한다.
     */
#ifndef MHZ19B_WARMUP_MS
#define MHZ19B_WARMUP_MS 60000
#endif
    static constexpr unsigned long WARMUP_MS = MHZ19B_WARMUP_MS;
    /*
     * MH-Z19B 내부 갱신 주기가 약 5초라 1초마다 쪼면 새 값도 안 나오면서
     * 통신 부하만 늘어난다. 2초로 늦춘다.
     */
    static constexpr unsigned long SAMPLE_INTERVAL_MS = 2000;

    /*
     * 500ms 로는 늦게 오는 응답을 놓친다. 2026-08-19 실물에서 1000ms 로 늘렸을
     * 때 잡히는 응답이 있었다.
     */
    static constexpr unsigned long RESPONSE_TIMEOUT_MS = 1000;

    // 한 번 실패했다고 다음 샘플까지 버리지 않는다. 즉시 재시도한다.
    static constexpr uint8_t READ_ATTEMPTS = 3;
};