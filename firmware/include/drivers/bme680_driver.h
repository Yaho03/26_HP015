#pragma once

#include <Arduino.h>
#include <Wire.h>
#include <bsec.h>

struct Bme680Data {
    float temperatureC = 0.0F;
    float humidityPct = 0.0F;
    float pressureHpa = 0.0F;
    float gasResistanceOhm = 0.0F;
    float iaq = 0.0F;
    uint8_t iaqAccuracy = 0;
    bool valid = false;
};

class Bme680Driver {
public:
    Bme680Driver(
        uint8_t sdaPin,
        uint8_t sclPin,
        uint8_t i2cAddress = BME68X_I2C_ADDR_HIGH
    );

    bool begin();
    bool update();

    bool hasNewData() const;
    void clearNewData();

    const Bme680Data& getData() const;

private:
    bool checkStatus() const;

    uint8_t sdaPin_;
    uint8_t sclPin_;
    uint8_t i2cAddress_;

    Bsec sensor_;
    Bme680Data data_;
    bool newData_ = false;
};