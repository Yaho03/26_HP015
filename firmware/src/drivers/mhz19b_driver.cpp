#include "drivers/mhz19b_driver.h"

namespace {

constexpr uint8_t READ_CO2_COMMAND[9] = {
    0xFF,
    0x01,
    0x86,
    0x00,
    0x00,
    0x00,
    0x00,
    0x00,
    0x79
};

}  // namespace

Mhz19bDriver::Mhz19bDriver(
    HardwareSerial& serialPort,
    const int8_t rxPin,
    const int8_t txPin
)
    : serialPort_(serialPort),
      rxPin_(rxPin),
      txPin_(txPin) {
}

void Mhz19bDriver::begin() {
    serialPort_.begin(
        9600,
        SERIAL_8N1,
        rxPin_,
        txPin_
    );

    delay(1000);

    startMs_ = millis();

    Serial.println("[MH-Z19B] Driver started.");
    Serial.println("[MH-Z19B] Warm-up: 60 seconds.");
}

bool Mhz19bDriver::update() {
    newData_ = false;

    const unsigned long now = millis();

    if (isWarmingUp()) {
        if (now - lastWarmupPrintMs_ >= 5000) {
            lastWarmupPrintMs_ = now;

            Serial.print("[MH-Z19B] Warming up: ");
            Serial.print(getRemainingWarmupSeconds());
            Serial.println(" seconds remaining.");
        }

        return false;
    }

    if (now - lastSampleMs_ < SAMPLE_INTERVAL_MS) {
        return false;
    }

    lastSampleMs_ = now;

    int co2Ppm = 0;

    if (!readCo2(co2Ppm)) {
        data_.valid = false;
        return false;
    }

    /*
     * 측정 범위 밖은 읽기 오류로 처리한다.
     * 체크섬이 맞아도 범위를 벗어난 값은 측정값이 아니다 — 2026-08-19 실물에서
     * 18,953ppm 이 정상값으로 발행되어 L3 경보까지 발화한 사례가 있었다.
     * SEN0322 드라이버가 이미 같은 방식으로 방어하고 있다.
     *
     * MH-Z19B 는 0~2000 / 0~5000 / 0~10000ppm 변종이 있으므로 상한은 빌드
     * 플래그로 둔다. 실제 구매 모델에 맞춰 MHZ19B_RANGE_PPM 을 지정할 것.
     */
    if (co2Ppm < 0 || co2Ppm > MHZ19B_RANGE_PPM) {
        Serial.print("[MH-Z19B] Out of range: ");
        Serial.print(co2Ppm);
        Serial.print(" ppm (range 0~");
        Serial.print(MHZ19B_RANGE_PPM);
        Serial.println(")");
        return false;
    }

    data_.co2Ppm = co2Ppm;
    data_.valid = true;

    newData_ = true;
    return true;
}

bool Mhz19bDriver::isWarmingUp() const {
    return millis() - startMs_ < WARMUP_MS;
}

unsigned long Mhz19bDriver::getRemainingWarmupSeconds() const {
    const unsigned long elapsed = millis() - startMs_;

    if (elapsed >= WARMUP_MS) {
        return 0;
    }

    return (WARMUP_MS - elapsed + 999) / 1000;
}

bool Mhz19bDriver::hasNewData() const {
    return newData_;
}

void Mhz19bDriver::clearNewData() {
    newData_ = false;
}

const Mhz19bData& Mhz19bDriver::getData() const {
    return data_;
}

uint8_t Mhz19bDriver::calculateChecksum(
    const uint8_t* packet
) {
    uint8_t sum = 0;

    for (int index = 1; index < 8; ++index) {
        sum += packet[index];
    }

    return static_cast<uint8_t>(0xFF - sum + 1);
}

/*
 * 프레임 동기화 방식으로 읽는다.
 *
 * 이전 구현은 9바이트가 모이면 앞에서부터 잘라 쓰고, 첫 바이트가 0xFF 가
 * 아니면 통째로 버렸다. 앞에 잡음 바이트가 하나만 끼어도 정상 응답이
 * 폐기된다 — 2026-08-19 실물에서 통신이 불안정한 개체의 수신율이 크게
 * 떨어진 원인이다.
 *
 * 대신 들어오는 바이트를 하나씩 흘려보며 0xFF 0x86 헤더를 찾아 정렬하고,
 * 거기서부터 9바이트를 맞춘다. 어긋난 프레임도 살려낸다.
 */
bool Mhz19bDriver::readFrame(int& co2Ppm) {
    while (serialPort_.available() > 0) {
        serialPort_.read();
    }

    serialPort_.write(
        READ_CO2_COMMAND,
        sizeof(READ_CO2_COMMAND)
    );

    serialPort_.flush();

    uint8_t response[9];
    uint8_t filled = 0;

    const unsigned long timeoutStart = millis();

    while (millis() - timeoutStart <= RESPONSE_TIMEOUT_MS) {
        if (serialPort_.available() <= 0) {
            delay(1);
            continue;
        }

        const uint8_t byteIn =
            static_cast<uint8_t>(serialPort_.read());

        // 헤더 정렬: 0xFF 를 만나기 전까지는 버린다.
        if (filled == 0) {
            if (byteIn != 0xFF) {
                continue;
            }
        } else if (filled == 1 && byteIn != 0x86) {
            // 0xFF 뒤가 0x86 이 아니면 그 바이트가 새 헤더일 수 있다.
            filled = (byteIn == 0xFF) ? 1 : 0;
            continue;
        }

        response[filled++] = byteIn;

        if (filled < sizeof(response)) {
            continue;
        }

        if (calculateChecksum(response) != response[8]) {
            Serial.println("[MH-Z19B] Checksum error.");
            return false;
        }

        co2Ppm =
            static_cast<int>(response[2]) * 256
            + response[3];

        return true;
    }

    return false;
}

bool Mhz19bDriver::readCo2(int& co2Ppm) {
    for (uint8_t attempt = 1; attempt <= READ_ATTEMPTS; ++attempt) {
        if (readFrame(co2Ppm)) {
            if (attempt > 1) {
                Serial.print("[MH-Z19B] Recovered on attempt ");
                Serial.println(attempt);
            }
            return true;
        }
        delay(30);
    }

    Serial.print("[MH-Z19B] No valid response after ");
    Serial.print(READ_ATTEMPTS);
    Serial.println(" attempts.");
    return false;
}