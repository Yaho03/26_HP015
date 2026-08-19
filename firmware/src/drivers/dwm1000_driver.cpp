#include "drivers/dwm1000_driver.h"

#include <cstring>

Dwm1000Driver::Dwm1000Driver(
    SPIClass& spi,
    const int8_t sckPin,
    const int8_t misoPin,
    const int8_t mosiPin,
    const int8_t csPin,
    const int8_t rstPin
)
    : spi_(spi),
      sckPin_(sckPin),
      misoPin_(misoPin),
      mosiPin_(mosiPin),
      csPin_(csPin),
      rstPin_(rstPin) {
}

bool Dwm1000Driver::begin() {
    pinMode(csPin_, OUTPUT);
    digitalWrite(csPin_, HIGH);

    spi_.begin(
        sckPin_,
        misoPin_,
        mosiPin_,
        csPin_
    );

    hardwareReset();

    return update();
}

bool Dwm1000Driver::update() {
    uint8_t raw[4] = {};
    readDeviceIdRaw(raw);

    memcpy(
        data_.rawBytes,
        raw,
        sizeof(raw)
    );

    data_.rawDeviceId =
        bytesToUint32(raw);

    data_.detected =
        data_.rawDeviceId == EXPECTED_DEVICE_ID;

    return data_.detected;
}

void Dwm1000Driver::hardwareReset() {
    pinMode(rstPin_, OUTPUT);
    digitalWrite(rstPin_, LOW);
    delay(10);

    digitalWrite(rstPin_, HIGH);
    delay(10);

    pinMode(rstPin_, INPUT);
    delay(10);
}

void Dwm1000Driver::readDeviceIdRaw(
    uint8_t bytes[4]
) {
    spi_.beginTransaction(
        SPISettings(
            SPI_SPEED_HZ,
            MSBFIRST,
            SPI_MODE0
        )
    );

    digitalWrite(csPin_, LOW);

    // DW1000 register 0x00 is DEV_ID. The expected bytes are 30 01 CA DE.
    spi_.transfer(0x00);
    for (uint8_t i = 0; i < 4; ++i) {
        bytes[i] =
            spi_.transfer(0x00);
    }

    digitalWrite(csPin_, HIGH);
    spi_.endTransaction();
}

uint32_t Dwm1000Driver::bytesToUint32(
    const uint8_t bytes[4]
) {
    return static_cast<uint32_t>(bytes[0])
        | (static_cast<uint32_t>(bytes[1]) << 8)
        | (static_cast<uint32_t>(bytes[2]) << 16)
        | (static_cast<uint32_t>(bytes[3]) << 24);
}

bool Dwm1000Driver::isDetected() const {
    return data_.detected;
}

const Dwm1000Data& Dwm1000Driver::getData() const {
    return data_;
}
