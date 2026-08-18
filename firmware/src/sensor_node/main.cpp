#include <Arduino.h>
#include <Wire.h>
#include <ArduinoJson.h>
#include <WiFi.h>
#include <MQTT.h>

#include "drivers/ads1115_mq_driver.h"
#include "drivers/bme680_driver.h"
#include "drivers/mhz19b_driver.h"
#include "sensors/calibration.h"

#include "config/node_config.h"
#include "config/network_config.h"

#include "mqtt/mqtt_envelope.h"
#include "mqtt/mqtt_topics.h"
#include "mqtt/mqtt_time.h"
#include "mqtt/ulid.h"

namespace {

// ============================================================
// Pins
// ============================================================

constexpr uint8_t SDA_PIN = 21;
constexpr uint8_t SCL_PIN = 22;

constexpr int8_t MHZ19B_RX_PIN = 16;
constexpr int8_t MHZ19B_TX_PIN = 17;


// ============================================================
// Wi-Fi / MQTT
// ============================================================

WiFiClient wifiClient;
// GAS Envelope가 약 900 bytes이므로 넉넉하게
MQTTClient mqttClient(2048);


// ============================================================
// Sensor drivers
// ============================================================

Ads1115MqDriver mqDriver(
    0x48,
    5.0F,
    10000.0F
);

Bme680Driver bmeDriver(
    SDA_PIN,
    SCL_PIN
);

HardwareSerial mhzSerial(2);

Mhz19bDriver mhzDriver(
    mhzSerial,
    MHZ19B_RX_PIN,
    MHZ19B_TX_PIN
);


// ============================================================
// Sensor state
// ============================================================

bool adsReady = false;
bool bmeReady = false;

Ads1115MqData latestMq;
Bme680Data latestBme;
Mhz19bData latestMhz;

bool hasMq = false;
bool hasBme = false;
bool hasMhz = false;


// ============================================================
// Envelope
// ============================================================

String bootId;

MqttEnvelopeBuilder* envelopeBuilder = nullptr;


// ============================================================
// Publish intervals
// ============================================================

unsigned long lastGasPublishMs = 0;
unsigned long lastEnvPublishMs = 0;
unsigned long lastStatusPublishMs = 0;
unsigned long lastMqCalibrationLogMs = 0;

constexpr unsigned long GAS_PUBLISH_INTERVAL_MS = 1000;
constexpr unsigned long ENV_PUBLISH_INTERVAL_MS = 3000;
constexpr unsigned long STATUS_PUBLISH_INTERVAL_MS = 10000;
constexpr unsigned long MQ_CALIBRATION_LOG_INTERVAL_MS = 10000;
// 24h/48h 물리 예열은 검증자가 교정 세션 전에 끝낸다는 전제다.
// 펌웨어 보조 출력은 부팅 직후부터 안정도와 R0 후보를 보여준다.
constexpr unsigned long MQ_CALIBRATION_WARMUP_MS = 0;

constexpr unsigned long NTP_RETRY_INITIAL_MS = 5000;
constexpr unsigned long NTP_RETRY_MAX_MS = 60000;
constexpr unsigned long NTP_SYNC_TIMEOUT_MS = 5000;

#ifndef MQ7_R0_OHM
#define MQ7_R0_OHM 0.0
#endif

#ifndef MQ136_R0_OHM
#define MQ136_R0_OHM 0.0
#endif

#ifndef MQ2_R0_OHM
#define MQ2_R0_OHM 0.0
#endif

#ifndef MQ7_CO_CURVE_A
#define MQ7_CO_CURVE_A 99.042
#endif

#ifndef MQ7_CO_CURVE_B
#define MQ7_CO_CURVE_B -1.518
#endif

#ifndef MQ136_H2S_CURVE_A
#define MQ136_H2S_CURVE_A 36.737
#endif

#ifndef MQ136_H2S_CURVE_B
#define MQ136_H2S_CURVE_B -3.536
#endif

// Clean-air Rs/R0 values from manufacturer datasheet sensitivity curves:
// Hanwei MQ-7 clean-air point ~= 27.5, Hanwei MQ-2 clean-air point = 9.83,
// Winsen/Hanwei MQ-136 clean-air point is read from the air point as ~= 3.4.
constexpr float MQ7_CLEAN_AIR_RS_R0 = 27.5F;
constexpr float MQ136_CLEAN_AIR_RS_R0 = 3.4F;
constexpr float MQ2_CLEAN_AIR_RS_R0 = 9.83F;

unsigned long lastNtpAttemptMs = 0;
unsigned long ntpRetryIntervalMs = NTP_RETRY_INITIAL_MS;

hp015::sensors::MqCalibrator mq7Calibrator(
    MQ7_CLEAN_AIR_RS_R0,
    MQ_CALIBRATION_WARMUP_MS
);

hp015::sensors::MqCalibrator mq136Calibrator(
    MQ136_CLEAN_AIR_RS_R0,
    MQ_CALIBRATION_WARMUP_MS
);

hp015::sensors::MqCalibrator mq2Calibrator(
    MQ2_CLEAN_AIR_RS_R0,
    MQ_CALIBRATION_WARMUP_MS
);

bool mq7CalibrationReported = false;
bool mq136CalibrationReported = false;
bool mq2CalibrationReported = false;


// ============================================================
// Connection payload
// ============================================================

String connectionPayload(const char* status, const char* reason) {
    JsonDocument document;
    document["schema_version"] = "1.1";
    document["node_id"] = NodeConfig::NODE_ID;
    document["status"] = status;
    document["reason"] = reason;
    document["boot_id"] = bootId;

    if (MqttTime::isSynced()) {
        document["timestamp"] = MqttTime::nowIso8601Utc();
    } else {
        document["timestamp"] = nullptr;
    }

    String payload;
    serializeJson(document, payload);
    return payload;
}

bool mqttConnectWithOptionalAuth(const char* clientId) {
    if (strlen(NetworkConfig::MQTT_USERNAME) == 0) {
        return mqttClient.connect(clientId);
    }

    return mqttClient.connect(
        clientId,
        NetworkConfig::MQTT_USERNAME,
        NetworkConfig::MQTT_PASSWORD
    );
}

bool retryNtpIfDue() {
    if (MqttTime::isSynced()) {
        return true;
    }

    if (WiFi.status() != WL_CONNECTED) {
        return false;
    }

    const unsigned long nowMs = millis();

    if (
        lastNtpAttemptMs != 0
        && nowMs - lastNtpAttemptMs < ntpRetryIntervalMs
    ) {
        return false;
    }

    lastNtpAttemptMs = nowMs;

    Serial.println("[TIME] NTP retry.");

    if (MqttTime::sync(NTP_SYNC_TIMEOUT_MS)) {
        ntpRetryIntervalMs = NTP_RETRY_INITIAL_MS;
        return true;
    }

    ntpRetryIntervalMs =
        min(
            ntpRetryIntervalMs * 2,
            NTP_RETRY_MAX_MS
        );

    return false;
}

bool ensureTimeSyncedForPublish(const char* label) {
    if (MqttTime::isSynced()) {
        return true;
    }

    if (retryNtpIfDue()) {
        return true;
    }

    Serial.print("[TIME] ");
    Serial.print(label);
    Serial.println(" skipped: NTP not synced.");

    return false;
}

float estimatePpm(
    const MqChannelData& channel,
    const float curveA,
    const float curveB
) {
    if (
        !channel.valid
        || channel.r0Ohm <= 0.0F
        || channel.rsR0Ratio <= 0.0F
    ) {
        return NAN;
    }

    return curveA * pow(channel.rsR0Ratio, curveB);
}

void configureMqCalibration() {
    mqDriver.setR0Values(
        static_cast<float>(MQ7_R0_OHM),
        static_cast<float>(MQ136_R0_OHM),
        static_cast<float>(MQ2_R0_OHM)
    );

    Serial.print("[MQ] R0 from build flags. MQ-7=");
    Serial.print(static_cast<float>(MQ7_R0_OHM));
    Serial.print(" ohm, MQ-136=");
    Serial.print(static_cast<float>(MQ136_R0_OHM));
    Serial.print(" ohm, MQ-2=");
    Serial.print(static_cast<float>(MQ2_R0_OHM));
    Serial.println(" ohm.");
}

void printMqCalibrator(
    const char* label,
    const MqChannelData& channel,
    const hp015::sensors::MqCalibrator& calibrator
) {
    Serial.print(label);

    if (!channel.valid) {
        Serial.print(" invalid");
        return;
    }

    Serial.print(" rs=");
    Serial.print(channel.rsOhm, 2);
    Serial.print(" avg60s=");
    Serial.print(calibrator.averageOhm(), 2);
    Serial.print(" spread=");
    Serial.print(calibrator.spreadPct(), 2);
    Serial.print("%");
    Serial.print(" r0_candidate=");
    Serial.print(calibrator.r0CandidateOhm(), 2);
}

void printMqCalibrationReady(
    const char* label,
    const float r0CandidateOhm
) {
    Serial.print("[MQ CAL] ");
    Serial.print(label);
    Serial.print(" stable for 5min. Copy R0 candidate to platformio.ini: ");
    Serial.print(r0CandidateOhm, 2);
    Serial.println(" ohm.");
}

void updateMqCalibrationAssist() {
    if (!hasMq) {
        return;
    }

    mq7Calibrator.update(latestMq.mq7.rsOhm);
    mq136Calibrator.update(latestMq.mq136.rsOhm);
    mq2Calibrator.update(latestMq.mq2.rsOhm);

    const unsigned long nowMs = millis();

    if (
        nowMs - lastMqCalibrationLogMs
        >= MQ_CALIBRATION_LOG_INTERVAL_MS
    ) {
        lastMqCalibrationLogMs =
            nowMs;

        Serial.print("[MQ CAL] ");
        printMqCalibrator("mq7", latestMq.mq7, mq7Calibrator);
        Serial.print(" | ");
        printMqCalibrator("mq136", latestMq.mq136, mq136Calibrator);
        Serial.print(" | ");
        printMqCalibrator("mq2", latestMq.mq2, mq2Calibrator);
        Serial.println();
    }

    if (
        !mq7CalibrationReported
        && mq7Calibrator.state() == hp015::sensors::CalibrationState::DONE
    ) {
        mq7CalibrationReported = true;
        printMqCalibrationReady("mq7", mq7Calibrator.r0Ohm());
    }

    if (
        !mq136CalibrationReported
        && mq136Calibrator.state() == hp015::sensors::CalibrationState::DONE
    ) {
        mq136CalibrationReported = true;
        printMqCalibrationReady("mq136", mq136Calibrator.r0Ohm());
    }

    if (
        !mq2CalibrationReported
        && mq2Calibrator.state() == hp015::sensors::CalibrationState::DONE
    ) {
        mq2CalibrationReported = true;
        printMqCalibrationReady("mq2", mq2Calibrator.r0Ohm());
    }
}


// ============================================================
// Wi-Fi
// ============================================================

void connectWifi() {
    if (WiFi.status() == WL_CONNECTED) {
        return;
    }

    Serial.println();
    Serial.print("[WiFi] Connecting to: ");
    Serial.println(NetworkConfig::WIFI_SSID);

    WiFi.mode(WIFI_STA);

    WiFi.begin(
        NetworkConfig::WIFI_SSID,
        NetworkConfig::WIFI_PASSWORD
    );

    const unsigned long startMs = millis();

    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");

        if (millis() - startMs > 20000) {
            Serial.println();
            Serial.println("[WiFi] Connection timeout.");
            return;
        }
    }

    Serial.println();
    Serial.println("[WiFi] Connected.");

    Serial.print("[WiFi] ESP32 IP: ");
    Serial.println(WiFi.localIP());

    Serial.print("[WiFi] RSSI: ");
    Serial.print(WiFi.RSSI());
    Serial.println(" dBm");
}


// ============================================================
// MQTT
// ============================================================

void connectMqtt() {
    if (mqttClient.connected()) {
        return;
    }

    if (WiFi.status() != WL_CONNECTED) {
        return;
    }

    Serial.print("[MQTT] Connecting to ");
    Serial.print(NetworkConfig::MQTT_BROKER);
    Serial.print(":");
    Serial.println(NetworkConfig::MQTT_PORT);

    String clientId =
        String(NodeConfig::NODE_ID)
        + "-"
        + String(
            static_cast<uint32_t>(
                ESP.getEfuseMac()
            ),
            HEX
        );

    const String connectionTopic =
        MqttTopics::connection(
            NodeConfig::NODE_ID
        );

    // -----------------------------
    // LWT
    // -----------------------------
    const String lwtPayload =
        connectionPayload("offline", "lwt");

    mqttClient.setWill(
        connectionTopic.c_str(),
        lwtPayload.c_str(),
        true,   // retained
        1       // QoS 1
    );

    const bool connected =
        mqttConnectWithOptionalAuth(
            clientId.c_str()
        );

    if (connected) {
        Serial.println(
            "[MQTT] Connected."
        );

        // 연결 성공 -> online
        const String onlinePayload =
            connectionPayload("online", "connect");

        const bool onlinePublished =
            mqttClient.publish(
                connectionTopic,
                onlinePayload,
                true,   // retained
                1       // QoS 1
            );

        if (onlinePublished) {
            Serial.println(
                "[MQTT] Online status published (QoS 1)."
            );
        } else {
            Serial.println(
                "[MQTT] Online status publish failed."
            );
        }

    } else {
        Serial.println(
            "[MQTT] Connection failed."
        );
    }
}


// ============================================================
// GAS message status
// ============================================================

MessageStatus getGasMessageStatus() {
    const bool mqOk =
        hasMq &&
        latestMq.valid;

    const bool bmeOk =
        hasBme &&
        latestBme.valid;

    const bool mhzOk =
        hasMhz &&
        latestMhz.valid &&
        !mhzDriver.isWarmingUp();

    if (
        mqOk &&
        bmeOk &&
        mhzOk
    ) {
        return MessageStatus::COMPLETE;
    }

    if (
        mqOk ||
        bmeOk ||
        mhzOk
    ) {
        return MessageStatus::PARTIAL;
    }

    return MessageStatus::DEGRADED;
}


// ============================================================
// ENV message status
// ============================================================

MessageStatus getEnvMessageStatus() {
    if (
        hasBme &&
        latestBme.valid
    ) {
        return MessageStatus::COMPLETE;
    }

    return MessageStatus::DEGRADED;
}


// ============================================================
// STATUS message status
// ============================================================

MessageStatus getStatusMessageStatus() {
    if (WiFi.status() == WL_CONNECTED) {
        return MessageStatus::COMPLETE;
    }

    return MessageStatus::DEGRADED;
}


// ============================================================
// GAS publish
// ============================================================

void publishGas() {
    if (!mqttClient.connected()) {
        Serial.println(
            "[MQTT] GAS skipped: MQTT disconnected."
        );
        return;
    }

    if (!ensureTimeSyncedForPublish("GAS")) {
        return;
    }

    if (envelopeBuilder == nullptr) {
        return;
    }

    JsonDocument document;

    const String now =
        MqttTime::nowIso8601Utc();

    const String messageId =
        Ulid::generate();

    JsonObject data =
        envelopeBuilder->begin(
            document,
            messageId,
            now,
            now,
            getGasMessageStatus(),
            true
        );


    // --------------------------------------------------------
    // MH-Z19B
    // --------------------------------------------------------

    if (
        hasMhz &&
        latestMhz.valid &&
        !mhzDriver.isWarmingUp()
    ) {
        data["co2_ppm"] =
            latestMhz.co2Ppm;
    } else {
        data["co2_ppm"] =
            nullptr;
    }


    // --------------------------------------------------------
    // MQ sensors
    // --------------------------------------------------------

    if (hasMq) {

        // MQ-7 -> CO contract fields
        data["co_raw_adc"] =
            latestMq.mq7.rawAdc;

        data["co_voltage_v"] =
            latestMq.mq7.voltageV;

        data["co_rs_ohm"] =
            latestMq.mq7.rsOhm;

        if (latestMq.mq7.r0Ohm > 0.0F) {
            data["co_rs_r0_ratio"] =
                latestMq.mq7.rsR0Ratio;
            data["co_calibration_status"] =
                "calibrated";

            const float coPpm =
                estimatePpm(
                    latestMq.mq7,
                    static_cast<float>(MQ7_CO_CURVE_A),
                    static_cast<float>(MQ7_CO_CURVE_B)
                );

            if (!isnan(coPpm) && isfinite(coPpm)) {
                data["co_ppm"] = coPpm;
            }
        } else {
            data["co_calibration_status"] =
                "uncalibrated";
        }

        // MQ-136 -> H2S contract fields
        data["h2s_raw_adc"] =
            latestMq.mq136.rawAdc;

        data["h2s_voltage_v"] =
            latestMq.mq136.voltageV;

        data["h2s_rs_ohm"] =
            latestMq.mq136.rsOhm;

        if (latestMq.mq136.r0Ohm > 0.0F) {
            data["h2s_rs_r0_ratio"] =
                latestMq.mq136.rsR0Ratio;
            data["h2s_calibration_status"] =
                "calibrated";

            const float h2sPpm =
                estimatePpm(
                    latestMq.mq136,
                    static_cast<float>(MQ136_H2S_CURVE_A),
                    static_cast<float>(MQ136_H2S_CURVE_B)
                );

            if (!isnan(h2sPpm) && isfinite(h2sPpm)) {
                data["h2s_ppm"] = h2sPpm;
            }
        } else {
            data["h2s_calibration_status"] =
                "uncalibrated";
        }

        // MQ-2
        data["mq2_raw_adc"] =
            latestMq.mq2.rawAdc;

        data["mq2_voltage_v"] =
            latestMq.mq2.voltageV;

        data["mq2_rs_ohm"] =
            latestMq.mq2.rsOhm;

        if (latestMq.mq2.r0Ohm > 0.0F) {
            data["mq2_rs_r0_ratio"] =
                latestMq.mq2.rsR0Ratio;
            data["mq2_calibration_status"] =
                "calibrated";
        } else {
            data["mq2_calibration_status"] =
                "uncalibrated";
        }

    } else {
        data["co_raw_adc"] = nullptr;
        data["co_voltage_v"] = nullptr;
        data["co_rs_ohm"] = nullptr;
        data["co_rs_r0_ratio"] = nullptr;
        data["co_calibration_status"] = "uncalibrated";

        data["h2s_raw_adc"] = nullptr;
        data["h2s_voltage_v"] = nullptr;
        data["h2s_rs_ohm"] = nullptr;
        data["h2s_rs_r0_ratio"] = nullptr;
        data["h2s_calibration_status"] = "uncalibrated";

        data["mq2_raw_adc"] = nullptr;
        data["mq2_voltage_v"] = nullptr;
        data["mq2_rs_ohm"] = nullptr;
        data["mq2_rs_r0_ratio"] = nullptr;
        data["mq2_calibration_status"] = "uncalibrated";
    }


    // --------------------------------------------------------
    // BME680 gas / IAQ
    // --------------------------------------------------------

    if (
        hasBme &&
        latestBme.valid
    ) {
        data["gas_resistance_ohm"] =
            latestBme.gasResistanceOhm;

        data["iaq_index"] =
            latestBme.iaq;

        data["iaq_accuracy"] =
            latestBme.iaqAccuracy;
    } else {
        data["gas_resistance_ohm"] =
            nullptr;

        data["iaq_index"] =
            nullptr;

        data["iaq_accuracy"] =
            nullptr;
    }


    // --------------------------------------------------------
    // quality.sensors
    // --------------------------------------------------------

    envelopeBuilder->addSensorQuality(
            document,
            "ads1115",
            adsReady
                ? SensorQuality::VALID
                : SensorQuality::NOT_CONNECTED
    );


    // MQ-7
    if (
        !hasMq ||
        !latestMq.mq7.valid
    ) {
        envelopeBuilder->addSensorQuality(
            document,
            "mq-7",
            SensorQuality::ERROR
        );

    } else if (
        latestMq.mq7.r0Ohm <= 0.0F
    ) {
        envelopeBuilder->addSensorQuality(
            document,
            "mq-7",
            SensorQuality::UNCALIBRATED
        );

    } else {
        envelopeBuilder->addSensorQuality(
            document,
            "mq-7",
            SensorQuality::VALID
        );
    }


    // MQ-136
    if (
        !hasMq ||
        !latestMq.mq136.valid
    ) {
        envelopeBuilder->addSensorQuality(
            document,
            "mq-136",
            SensorQuality::ERROR
        );

    } else if (
        latestMq.mq136.r0Ohm <= 0.0F
    ) {
        envelopeBuilder->addSensorQuality(
            document,
            "mq-136",
            SensorQuality::UNCALIBRATED
        );

    } else {
        envelopeBuilder->addSensorQuality(
            document,
            "mq-136",
            SensorQuality::VALID
        );
    }


    // MQ-2
    if (
        !hasMq ||
        !latestMq.mq2.valid
    ) {
        envelopeBuilder->addSensorQuality(
            document,
            "mq-2",
            SensorQuality::ERROR
        );

    } else if (
        latestMq.mq2.r0Ohm <= 0.0F
    ) {
        envelopeBuilder->addSensorQuality(
            document,
            "mq-2",
            SensorQuality::UNCALIBRATED
        );

    } else {
        envelopeBuilder->addSensorQuality(
            document,
            "mq-2",
            SensorQuality::VALID
        );
    }


    // MH-Z19B
    if (mhzDriver.isWarmingUp()) {
        envelopeBuilder->addSensorQuality(
            document,
            "mh-z19b",
            SensorQuality::WARMING_UP
        );

    } else if (
        !hasMhz ||
        !latestMhz.valid
    ) {
        envelopeBuilder->addSensorQuality(
            document,
            "mh-z19b",
            SensorQuality::ERROR
        );

    } else {
        envelopeBuilder->addSensorQuality(
            document,
            "mh-z19b",
            SensorQuality::VALID
        );
    }


    // BME680
    if (!bmeReady) {
        envelopeBuilder->addSensorQuality(
            document,
            "bme680",
            SensorQuality::NOT_CONNECTED
        );

    } else if (
        !hasBme ||
        !latestBme.valid
    ) {
        envelopeBuilder->addSensorQuality(
            document,
            "bme680",
            SensorQuality::ERROR
        );

    } else {
        envelopeBuilder->addSensorQuality(
            document,
            "bme680",
            SensorQuality::VALID
        );
    }


    // --------------------------------------------------------
    // Serialize + publish
    // --------------------------------------------------------

    String payload;

    serializeJson(
        document,
        payload
    );

    const String topic =
        MqttTopics::sensorGas(
            NodeConfig::NODE_ID
        );

    Serial.print("[MQTT GAS] ");
    Serial.println(payload);

    const bool published =
        mqttClient.publish(
            topic,
            payload,
            false,
            1
        );

    if (!published) {
        Serial.println(
            "[MQTT] GAS publish failed."
        );
    }
}


// ============================================================
// ENV publish
// ============================================================

void publishEnv() {
    if (!mqttClient.connected()) {
        return;
    }

    if (!ensureTimeSyncedForPublish("ENV")) {
        return;
    }

    if (
        !hasBme ||
        !latestBme.valid
    ) {
        return;
    }

    if (envelopeBuilder == nullptr) {
        return;
    }

    JsonDocument document;

    const String now =
        MqttTime::nowIso8601Utc();

    JsonObject data =
        envelopeBuilder->begin(
            document,
            Ulid::generate(),
            now,
            now,
            getEnvMessageStatus(),
            true
        );

    data["temperature_c"] =
        latestBme.temperatureC;

    data["humidity_pct"] =
        latestBme.humidityPct;

    data["pressure_hpa"] =
        latestBme.pressureHpa;


    envelopeBuilder->addSensorQuality(
        document,
        "bme680",
        SensorQuality::VALID
    );


    String payload;

    serializeJson(
        document,
        payload
    );

    const String topic =
        MqttTopics::sensorEnv(
            NodeConfig::NODE_ID
        );

    Serial.print("[MQTT ENV] ");
    Serial.println(payload);

    const bool published =
        mqttClient.publish(
            topic,
            payload,
            false,
            1
        );

    if (!published) {
        Serial.println(
            "[MQTT] ENV publish failed."
        );
    }
}


// ============================================================
// STATUS publish
// ============================================================

void publishStatus() {
    if (!mqttClient.connected()) {
        return;
    }

    if (!ensureTimeSyncedForPublish("STATUS")) {
        return;
    }

    if (envelopeBuilder == nullptr) {
        return;
    }

    JsonDocument document;

    const String now =
        MqttTime::nowIso8601Utc();

    JsonObject data =
        envelopeBuilder->begin(
            document,
            Ulid::generate(),
            now,
            now,
            getStatusMessageStatus(),
            true
        );


    // --------------------------------------------------------
    // 고정 센서 노드는 상시 전원이다. ingest_status의 필수 int 계약을
    // 유지하면서 대시보드가 방전 상태로 오해하지 않도록 100으로 보낸다.
    data["battery_pct"] =
        100;


    // --------------------------------------------------------
    // Wi-Fi RSSI
    // --------------------------------------------------------

    data["wifi_rssi_dbm"] =
        WiFi.RSSI();


    // --------------------------------------------------------
    // Uptime
    // --------------------------------------------------------

    data["uptime_s"] =
        millis() / 1000UL;

    data["free_heap_bytes"] =
        ESP.getFreeHeap();

    JsonArray sensorsOnline =
        data["sensors_online"].to<JsonArray>();

    JsonArray sensorsError =
        data["sensors_error"].to<JsonArray>();

    if (adsReady) {
        sensorsOnline.add("ads1115");
    } else {
        sensorsError.add("ads1115");
    }

    if (bmeReady) {
        sensorsOnline.add("bme680");
    } else {
        sensorsError.add("bme680");
    }

    if (hasMhz && latestMhz.valid && !mhzDriver.isWarmingUp()) {
        sensorsOnline.add("mh-z19b");
    } else {
        sensorsError.add("mh-z19b");
    }

    if (hasMq && latestMq.mq7.valid) {
        sensorsOnline.add("mq-7");
    } else {
        sensorsError.add("mq-7");
    }

    if (hasMq && latestMq.mq136.valid) {
        sensorsOnline.add("mq-136");
    } else {
        sensorsError.add("mq-136");
    }

    if (hasMq && latestMq.mq2.valid) {
        sensorsOnline.add("mq-2");
    } else {
        sensorsError.add("mq-2");
    }


    // --------------------------------------------------------
    // Quality
    // --------------------------------------------------------

    envelopeBuilder->addSensorQuality(
        document,
        "mh-z19b",
        hasMhz && latestMhz.valid
            ? SensorQuality::VALID
            : SensorQuality::ERROR
    );

    envelopeBuilder->addSensorQuality(
        document,
        "mq-7",
        hasMq && latestMq.mq7.valid
            ? SensorQuality::VALID
            : SensorQuality::ERROR
    );

    envelopeBuilder->addSensorQuality(
        document,
        "mq-136",
        hasMq && latestMq.mq136.valid
            ? SensorQuality::VALID
            : SensorQuality::ERROR
    );

    envelopeBuilder->addSensorQuality(
        document,
        "mq-2",
        hasMq && latestMq.mq2.valid
            ? SensorQuality::VALID
            : SensorQuality::ERROR
    );

    envelopeBuilder->addSensorQuality(
        document,
        "bme680",
        bmeReady
            ? SensorQuality::VALID
            : SensorQuality::NOT_CONNECTED
    );

    envelopeBuilder->addSensorQuality(
        document,
        "ads1115",
        adsReady
            ? SensorQuality::VALID
            : SensorQuality::NOT_CONNECTED
    );

    envelopeBuilder->addSensorQuality(
        document,
        "dwm1000",
        SensorQuality::NOT_CONNECTED
    );


    // --------------------------------------------------------
    // Serialize + publish
    // --------------------------------------------------------

    String payload;

    serializeJson(
        document,
        payload
    );

    const String topic =
        MqttTopics::sensorStatus(
            NodeConfig::NODE_ID
        );

    Serial.print("[MQTT STATUS] ");
    Serial.println(payload);

    const bool published =
        mqttClient.publish(
            topic,
            payload,
            false,
            1
        );

    if (!published) {
        Serial.println(
            "[MQTT] STATUS publish failed."
        );
    }
}

} // namespace


// ============================================================
// SETUP
// ============================================================

void setup() {
    Serial.begin(115200);
    delay(1500);

    Serial.println();
    Serial.println(
        "[SYSTEM] Sensor-node Envelope v1.1 + Status/LWT"
    );


    // ========================================================
    // Wi-Fi
    // ========================================================

    connectWifi();


    // ========================================================
    // NTP
    // ========================================================

    bool timeSynced = false;

    if (
        WiFi.status() ==
        WL_CONNECTED
    ) {
        timeSynced =
            MqttTime::sync(10000);
    }

    Serial.print("[TIME] Synced: ");
    Serial.println(
        timeSynced
            ? "true"
            : "false"
    );


    // ========================================================
    // boot_id
    // ========================================================

    bootId =
        Ulid::generate();

    Serial.print("[SYSTEM] boot_id: ");
    Serial.println(bootId);


    // ========================================================
    // Envelope builder
    // ========================================================

    envelopeBuilder =
        new MqttEnvelopeBuilder(
            NodeConfig::NODE_ID,
            bootId,
            SourceMode::LIVE
        );


    // ========================================================
    // MQTT
    // ========================================================

    mqttClient.begin(
        NetworkConfig::MQTT_BROKER,
        NetworkConfig::MQTT_PORT,
        wifiClient
    );

    connectMqtt();


    // ========================================================
    // I2C
    // ========================================================

    Wire.begin(
        SDA_PIN,
        SCL_PIN
    );

    Wire.setClock(
        100000
    );


    // ========================================================
    // ADS1115 + MQ
    // ========================================================

    Serial.println(
        "[SYSTEM] Initializing ADS1115 + MQ..."
    );

    adsReady =
        mqDriver.begin();

    if (adsReady) {
        configureMqCalibration();
        mq7Calibrator.begin();
        mq136Calibrator.begin();
        mq2Calibrator.begin();

        Serial.println(
            "[SYSTEM] ADS1115 + MQ ready."
        );
    } else {
        Serial.println(
            "[SYSTEM] ADS1115 + MQ initialization failed."
        );
    }


    // ========================================================
    // BME680
    // ========================================================

    Serial.println(
        "[SYSTEM] Initializing BME680..."
    );

    bmeReady =
        bmeDriver.begin();

    if (bmeReady) {
        Serial.println(
            "[SYSTEM] BME680 ready."
        );
    } else {
        Serial.println(
            "[SYSTEM] BME680 initialization failed."
        );
    }


    // ========================================================
    // MH-Z19B
    // ========================================================

    Serial.println(
        "[SYSTEM] Initializing MH-Z19B..."
    );

    mhzDriver.begin();

    Serial.println(
        "[SYSTEM] MH-Z19B started."
    );


    Serial.println();
    Serial.println(
        "[SYSTEM] Integration test running."
    );

    Serial.println(
        "[SYSTEM] GAS 1s / ENV 3s / STATUS 10s"
    );

    Serial.println(
        "[SYSTEM] LWT online/offline enabled."
    );
}


// ============================================================
// LOOP
// ============================================================

void loop() {

    // ========================================================
    // Wi-Fi reconnect
    // ========================================================

    if (
        WiFi.status() !=
        WL_CONNECTED
    ) {
        connectWifi();
    }

    retryNtpIfDue();


    // ========================================================
    // MQTT reconnect
    // ========================================================

    if (
        !mqttClient.connected()
    ) {
        connectMqtt();
    }

    mqttClient.loop();


    // ========================================================
    // ADS1115 + MQ
    // ========================================================

    if (adsReady) {
        if (mqDriver.update()) {
            if (mqDriver.hasNewData()) {

                latestMq =
                    mqDriver.getData();

                hasMq = true;

                updateMqCalibrationAssist();

                mqDriver.clearNewData();
            }
        }
    }


    // ========================================================
    // BME680
    // ========================================================

    if (bmeReady) {
        if (bmeDriver.update()) {
            if (bmeDriver.hasNewData()) {

                latestBme =
                    bmeDriver.getData();

                hasBme = true;

                bmeDriver.clearNewData();
            }
        }
    }


    // ========================================================
    // MH-Z19B
    // ========================================================

    if (mhzDriver.update()) {
        if (mhzDriver.hasNewData()) {

            latestMhz =
                mhzDriver.getData();

            hasMhz = true;

            mhzDriver.clearNewData();
        }
    }


    // ========================================================
    // GAS every 1 second
    // ========================================================

    if (
        millis() - lastGasPublishMs
        >= GAS_PUBLISH_INTERVAL_MS
    ) {
        lastGasPublishMs =
            millis();

        publishGas();
    }


    // ========================================================
    // ENV every 3 seconds
    // ========================================================

    if (
        millis() - lastEnvPublishMs
        >= ENV_PUBLISH_INTERVAL_MS
    ) {
        lastEnvPublishMs =
            millis();

        publishEnv();
    }


    // ========================================================
    // STATUS every 10 seconds
    // ========================================================

    if (
        millis() - lastStatusPublishMs
        >= STATUS_PUBLISH_INTERVAL_MS
    ) {
        lastStatusPublishMs =
            millis();

        publishStatus();
    }


    delay(1);
}
