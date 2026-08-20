#include "drivers/bme680_driver.h"

Bme680Driver::Bme680Driver(
    const uint8_t sdaPin,
    const uint8_t sclPin,
    const uint8_t i2cAddress
)
    : sdaPin_(sdaPin),
      sclPin_(sclPin),
      i2cAddress_(i2cAddress) {
}

bool Bme680Driver::begin() {
    Wire.begin(sdaPin_, sclPin_);

    sensor_.begin(i2cAddress_, Wire);

    if (!checkStatus()) {
        Serial.println("[BME680] Initialization failed.");
        return false;
    }

    bsec_virtual_sensor_t sensorList[] = {
        BSEC_OUTPUT_SENSOR_HEAT_COMPENSATED_TEMPERATURE,
        BSEC_OUTPUT_SENSOR_HEAT_COMPENSATED_HUMIDITY,
        BSEC_OUTPUT_RAW_PRESSURE,
        BSEC_OUTPUT_RAW_GAS,
        BSEC_OUTPUT_IAQ
    };

    sensor_.updateSubscription(
        sensorList,
        sizeof(sensorList) / sizeof(sensorList[0]),
        BSEC_SAMPLE_RATE_LP
    );

    if (!checkStatus()) {
        Serial.println("[BME680] Subscription failed.");
        return false;
    }

    Serial.println("[BME680] Initialization successful.");
    return true;
}

bool Bme680Driver::update() {
    newData_ = false;

    if (!sensor_.run()) {
        checkStatus();
        return false;
    }

    data_.temperatureC = sensor_.temperature;
    data_.humidityPct = sensor_.humidity;
    data_.pressureHpa = sensor_.pressure / 100.0F;
    data_.gasResistanceOhm = sensor_.gasResistance;
    data_.iaq = sensor_.iaq;
    data_.iaqAccuracy = sensor_.iaqAccuracy;
    data_.valid = true;

    newData_ = true;
    return true;
}

bool Bme680Driver::hasNewData() const {
    return newData_;
}

void Bme680Driver::clearNewData() {
    newData_ = false;
}

const Bme680Data& Bme680Driver::getData() const {
    return data_;
}

bool Bme680Driver::checkStatus() const {
    bool success = true;

    if (sensor_.bsecStatus < BSEC_OK) {
        Serial.print("[BME680] BSEC error: ");
        Serial.println(sensor_.bsecStatus);
        success = false;
    } else if (sensor_.bsecStatus > BSEC_OK) {
        Serial.print("[BME680] BSEC warning: ");
        Serial.println(sensor_.bsecStatus);
    }

    if (sensor_.bme68xStatus < BME68X_OK) {
        Serial.print("[BME680] Sensor error: ");
        Serial.println(sensor_.bme68xStatus);
        success = false;
    } else if (sensor_.bme68xStatus > BME68X_OK) {
        Serial.print("[BME680] Sensor warning: ");
        Serial.println(sensor_.bme68xStatus);
    }

    return success;
}