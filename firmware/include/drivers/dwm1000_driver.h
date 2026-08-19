#pragma once

#include <Arduino.h>
#include <SPI.h>

struct Dwm1000Data {
    uint8_t rawBytes[4] = {};
    uint32_t rawDeviceId = 0;
    bool detected = false;
};

class Dwm1000Driver {
public:
    Dwm1000Driver(
        SPIClass& spi,
        int8_t sckPin,
        int8_t misoPin,
        int8_t mosiPin,
        int8_t csPin,
        int8_t rstPin
    );

    bool begin();
    bool update();

    bool isDetected() const;
    const Dwm1000Data& getData() const;

private:
    void hardwareReset();
    void readDeviceIdRaw(uint8_t bytes[4]);

    static uint32_t bytesToUint32(const uint8_t bytes[4]);

    SPIClass& spi_;
    int8_t sckPin_;
    int8_t misoPin_;
    int8_t mosiPin_;
    int8_t csPin_;
    int8_t rstPin_;
    Dwm1000Data data_;

    static constexpr uint32_t SPI_SPEED_HZ = 1000000;
    static constexpr uint32_t EXPECTED_DEVICE_ID = 0xDECA0130;
};
