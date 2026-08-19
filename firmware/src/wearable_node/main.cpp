#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <MQTT.h>
#include <SPI.h>
#include <ArduinoJson.h>

#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>

#include "config/network_config.h"
#include "drivers/dwm1000_ranging_driver.h"
#include "drivers/sen0322_driver.h"
#include "mqtt/mqtt_topics.h"
#include "mqtt/mqtt_time.h"
#include "mqtt/ulid.h"

// ============================================================
// Configuration
// ============================================================

constexpr char NODE_ID[] = "wearable-01";

constexpr uint8_t SDA_PIN = 21;
constexpr uint8_t SCL_PIN = 22;

constexpr int8_t DWM1000_SCK_PIN = 18;
constexpr int8_t DWM1000_MISO_PIN = 19;
constexpr int8_t DWM1000_MOSI_PIN = 23;
constexpr int8_t DWM1000_CS_PIN = 5;
constexpr int8_t DWM1000_RST_PIN = 27;
constexpr int8_t DWM1000_IRQ_PIN = 26;

#ifndef DWM1000_EUI
#define DWM1000_EUI "10:00:22:EA:82:60:3B:9C"
#endif

#ifndef DWM1000_SHORT_ADDRESS
#define DWM1000_SHORT_ADDRESS 4096
#endif

// SEN0322
#define OXYGEN_I2C_ADDRESS ADDRESS_3

constexpr uint8_t OXYGEN_COLLECT_NUMBER = 10;

constexpr unsigned long IMU_INTERVAL_MS = 200;     // 5 Hz
constexpr unsigned long O2_INTERVAL_MS = 1000;    // 1 Hz
constexpr unsigned long STATUS_INTERVAL_MS = 10000;
constexpr unsigned long DWM1000_CHECK_INTERVAL_MS = 5000;
constexpr unsigned long UWB_PUBLISH_INTERVAL_MS = 200;
constexpr unsigned long UWB_RANGE_MAX_AGE_MS = 1000;
constexpr uint8_t UWB_MIN_RANGES_FOR_POSITION = 3;

constexpr unsigned long NTP_RETRY_INITIAL_MS = 5000;
constexpr unsigned long NTP_RETRY_MAX_MS = 60000;
constexpr unsigned long NTP_SYNC_TIMEOUT_MS = 5000;


// ============================================================
// Network / MQTT
// ============================================================

WiFiClient wifiClient;

// JSON 크기는 작지만 여유 있게
MQTTClient mqttClient(1024);


// ============================================================
// Sensors
// ============================================================

Adafruit_MPU6050 mpu;
Sen0322Driver oxygenDriver(
    OXYGEN_I2C_ADDRESS,
    OXYGEN_COLLECT_NUMBER
);
Dwm1000RangingDriver dwm1000Ranging(
    Dwm1000Role::TAG_NODE,
    DWM1000_EUI,
    DWM1000_SHORT_ADDRESS,
    DWM1000_SCK_PIN,
    DWM1000_MISO_PIN,
    DWM1000_MOSI_PIN,
    DWM1000_CS_PIN,
    DWM1000_RST_PIN,
    DWM1000_IRQ_PIN
);

bool mpuReady = false;
bool oxygenReady = false;
bool dwm1000Ready = false;

Sen0322Data latestOxygen;
bool hasOxygen = false;


// ============================================================
// Timing
// ============================================================

unsigned long lastImuMs = 0;
unsigned long lastO2Ms = 0;
unsigned long lastStatusMs = 0;
unsigned long lastDwm1000CheckMs = 0;
unsigned long lastUwbPublishMs = 0;
unsigned long lastUwbSkipLogMs = 0;

unsigned long lastNtpAttemptMs = 0;
unsigned long ntpRetryIntervalMs = NTP_RETRY_INITIAL_MS;


// ============================================================
// Time
// ============================================================

void logDwm1000Status(
    const char* prefix
) {
    Serial.print("[DWM1000] ");
    Serial.print(prefix);
    Serial.print(": ready=");
    Serial.print(
        dwm1000Ranging.isReady()
            ? "true"
            : "false"
    );
    Serial.print(", role=");
    Serial.print(
        dwm1000Ranging.roleName()
    );
    Serial.print(", eui=");
    Serial.print(
        dwm1000Ranging.eui()
    );
    Serial.print(", device=");
    Serial.println(
        dwm1000Ranging.deviceIdentifier()
    );
}

bool retryNtpIfDue() {
    if (MqttTime::isSynced()) {
        return true;
    }

    if (WiFi.status() != WL_CONNECTED) {
        return false;
    }

    const unsigned long nowMs =
        millis();

    if (
        lastNtpAttemptMs != 0
        && nowMs - lastNtpAttemptMs < ntpRetryIntervalMs
    ) {
        return false;
    }

    lastNtpAttemptMs =
        nowMs;

    Serial.println(
        "[TIME] NTP retry."
    );

    if (
        MqttTime::sync(
            NTP_SYNC_TIMEOUT_MS
        )
    ) {
        ntpRetryIntervalMs =
            NTP_RETRY_INITIAL_MS;
        return true;
    }

    ntpRetryIntervalMs =
        min(
            ntpRetryIntervalMs * 2,
            NTP_RETRY_MAX_MS
        );

    return false;
}

bool ensureTimeSyncedForPublish(
    const char* label
) {
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


// ============================================================
// Wi-Fi
// ============================================================

void connectWifi() {

    if (WiFi.status() == WL_CONNECTED) {
        return;
    }

    Serial.print("[WiFi] Connecting to ");
    Serial.println(NetworkConfig::WIFI_SSID);

    WiFi.mode(WIFI_STA);

    WiFi.begin(
        NetworkConfig::WIFI_SSID,
        NetworkConfig::WIFI_PASSWORD
    );

    unsigned long startMs = millis();

    while (WiFi.status() != WL_CONNECTED) {

        delay(500);
        Serial.print(".");

        if (millis() - startMs >= 20000) {

            Serial.println();
            Serial.println("[WiFi] Connection timeout.");

            return;
        }
    }

    Serial.println();
    Serial.println("[WiFi] Connected.");

    Serial.print("[WiFi] IP: ");
    Serial.println(WiFi.localIP());
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

    Serial.print("[MQTT] Connecting... ");

    String clientId =
        String(NODE_ID)
        + "-"
        + String(
            static_cast<uint32_t>(
                ESP.getEfuseMac()
            ),
            HEX
        );

    if (mqttClient.connect(
            clientId.c_str(),
            NetworkConfig::MQTT_USERNAME,
            NetworkConfig::MQTT_PASSWORD
        )) {

        Serial.println("connected.");

    } else {

        Serial.println("failed.");
    }
}


// ============================================================
// IMU publish
// ============================================================

void publishImu() {

    if (!mpuReady || !mqttClient.connected()) {
        return;
    }

    if (!ensureTimeSyncedForPublish("IMU")) {
        return;
    }

    sensors_event_t accel;
    sensors_event_t gyro;
    sensors_event_t temperature;

    mpu.getEvent(
        &accel,
        &gyro,
        &temperature
    );

    // Adafruit MPU6050 acceleration = m/s²
    // 우리가 기존에 쓰던 형태처럼 g 단위로 변환
    constexpr float GRAVITY = 9.80665F;

    float ax =
        accel.acceleration.x / GRAVITY;

    float ay =
        accel.acceleration.y / GRAVITY;

    float az =
        accel.acceleration.z / GRAVITY;

    float magnitude =
        sqrt(
            ax * ax +
            ay * ay +
            az * az
        );

    // Adafruit gyro = rad/s
    // 기존 출력처럼 degree/s로 변환
    float gx =
        gyro.gyro.x * 180.0F / PI;

    float gy =
        gyro.gyro.y * 180.0F / PI;

    float gz =
        gyro.gyro.z * 180.0F / PI;


    JsonDocument document;

    document["node_id"] = NODE_ID;

    document["message_id"] =
        Ulid::generate();

    document["sampled_at"] =
        MqttTime::nowIso8601Utc();

    JsonObject data =
        document["data"].to<JsonObject>();

    data["ax"] = ax;
    data["ay"] = ay;
    data["az"] = az;

    data["magnitude"] =
        magnitude;

    data["gx"] = gx;
    data["gy"] = gy;
    data["gz"] = gz;


    String payload;

    serializeJson(
        document,
        payload
    );

    bool ok =
        mqttClient.publish(
            MqttTopics::wearableImu(NODE_ID),
            payload,
            false,
            1
        );

    if (ok) {

        Serial.print("[IMU MQTT] ");
        Serial.println(payload);

    } else {

        Serial.println(
            "[MQTT] IMU publish failed."
        );
    }
}


// ============================================================
// O2 publish
// ============================================================

void publishOxygen() {

    if (!oxygenReady || !mqttClient.connected()) {
        return;
    }

    if (!ensureTimeSyncedForPublish("O2")) {
        return;
    }


    JsonDocument document;

    document["node_id"] =
        NODE_ID;

    document["message_id"] =
        Ulid::generate();

    document["sampled_at"] =
        MqttTime::nowIso8601Utc();

    JsonObject data =
        document["data"].to<JsonObject>();

    JsonObject quality =
        document["quality"].to<JsonObject>();

    JsonObject sensors =
        quality["sensors"].to<JsonObject>();

    if (
        hasOxygen &&
        latestOxygen.valid
    ) {
        data["o2_pct"] =
            latestOxygen.o2Pct;

        sensors["sen0322"] =
            "valid";
    } else {
        sensors["sen0322"] =
            "error";

        Serial.println(
            "[SEN0322] O2 publish without o2_pct: invalid reading."
        );
    }


    String payload;

    serializeJson(
        document,
        payload
    );


    bool ok =
        mqttClient.publish(
            MqttTopics::wearableVital(NODE_ID),
            payload,
            false,
            1
        );


    if (ok) {

        Serial.print("[O2 MQTT] ");
        Serial.println(payload);

    } else {

        Serial.println(
            "[MQTT] O2 publish failed."
        );
    }
}


// ============================================================
// Status
// ============================================================

void publishStatus() {

    if (!mqttClient.connected()) {
        return;
    }

    if (!ensureTimeSyncedForPublish("WEARABLE STATUS")) {
        return;
    }

    JsonDocument document;

    document["node_id"] =
        NODE_ID;

    document["sampled_at"] =
        MqttTime::nowIso8601Utc();

    JsonObject data =
        document["data"].to<JsonObject>();

    data["wifi_rssi"] =
        WiFi.RSSI();

    data["uptime_s"] =
        millis() / 1000UL;

    data["mpu6050_ready"] =
        mpuReady;

    data["sen0322_ready"] =
        oxygenReady;

    data["dwm1000_ready"] =
        dwm1000Ready;

    data["dwm1000_device_id"] =
        dwm1000Ranging.deviceIdentifier();

    data["dwm1000_role"] =
        dwm1000Ranging.roleName();


    String payload;

    serializeJson(
        document,
        payload
    );

    mqttClient.publish(
        String("wearable/") + NODE_ID + "/status",
        payload,
        false,
        1
    );
}


// ============================================================
// UWB ranging publish
// ============================================================

void publishRanging() {
    if (
        !dwm1000Ready
        || !mqttClient.connected()
        || !dwm1000Ranging.hasNewRange()
    ) {
        return;
    }

    if (!ensureTimeSyncedForPublish("UWB RANGING")) {
        return;
    }

    Dwm1000Range ranges[
        Dwm1000RangingDriver::MAX_ANCHOR_RANGES
    ];

    const size_t count =
        dwm1000Ranging.copyFreshRanges(
            ranges,
            Dwm1000RangingDriver::MAX_ANCHOR_RANGES,
            UWB_RANGE_MAX_AGE_MS
        );

    if (count < UWB_MIN_RANGES_FOR_POSITION) {
        const unsigned long nowMs =
            millis();

        if (nowMs - lastUwbSkipLogMs >= DWM1000_CHECK_INTERVAL_MS) {
            lastUwbSkipLogMs =
                nowMs;

            Serial.print(
                "[DWM1000] ranging publish skipped: fresh anchors="
            );
            Serial.println(count);
        }
        return;
    }

    JsonDocument document;

    document["schema_version"] =
        "1.1";
    document["node_id"] =
        NODE_ID;
    document["message_id"] =
        Ulid::generate();
    document["sampled_at"] =
        MqttTime::nowIso8601Utc();
    document["source_mode"] =
        "live";

    JsonObject data =
        document["data"].to<JsonObject>();

    JsonArray jsonRanges =
        data["ranges"].to<JsonArray>();

    for (size_t i = 0; i < count; ++i) {
        JsonObject entry =
            jsonRanges.add<JsonObject>();

        entry["anchor_id"] =
            ranges[i].anchorId;
        entry["distance_m"] =
            ranges[i].distanceM;
        entry["rx_power_dbm"] =
            ranges[i].rxPowerDbm;
    }

    data["method"] =
        "ds_twr";

    JsonObject quality =
        document["quality"].to<JsonObject>();

    JsonObject sensors =
        quality["sensors"].to<JsonObject>();

    sensors["dwm1000"] =
        "valid";

    String payload;

    serializeJson(
        document,
        payload
    );

    const bool ok =
        mqttClient.publish(
            MqttTopics::wearableRanging(NODE_ID),
            payload,
            false,
            1
        );

    if (ok) {
        dwm1000Ranging.clearNewRangeFlag();

        Serial.print("[UWB MQTT] ");
        Serial.println(payload);
    } else {
        Serial.println(
            "[MQTT] UWB ranging publish failed."
        );
    }
}


// ============================================================
// SETUP
// ============================================================

void setup() {

    Serial.begin(115200);

    delay(1500);


    Serial.println();
    Serial.println(
        "[SYSTEM] Wearable MQTT node"
    );


    // --------------------------------------------------------
    // I2C
    // --------------------------------------------------------

    Wire.begin(
        SDA_PIN,
        SCL_PIN
    );

    Wire.setClock(
        100000
    );


    // --------------------------------------------------------
    // MPU6050
    // --------------------------------------------------------

    Serial.println(
        "[MPU6050] Initializing..."
    );

    mpuReady =
        mpu.begin();

    if (mpuReady) {

        Serial.println(
            "[MPU6050] Ready."
        );

        mpu.setAccelerometerRange(
            MPU6050_RANGE_8_G
        );

        mpu.setGyroRange(
            MPU6050_RANGE_500_DEG
        );

        mpu.setFilterBandwidth(
            MPU6050_BAND_21_HZ
        );

    } else {

        Serial.println(
            "[MPU6050] Not detected."
        );
    }


    // --------------------------------------------------------
    // SEN0322
    // --------------------------------------------------------

    Serial.println(
        "[SEN0322] Initializing..."
    );

    oxygenReady =
        oxygenDriver.begin();

    if (oxygenReady) {

        Serial.println(
            "[SEN0322] Ready."
        );

    } else {

        Serial.println(
            "[SEN0322] Not detected."
        );
    }


    // --------------------------------------------------------
    // DWM1000
    // --------------------------------------------------------

    Serial.println(
        "[DWM1000] Initializing..."
    );

    dwm1000Ready =
        dwm1000Ranging.begin();

    logDwm1000Status(
        dwm1000Ranging.isReady()
            ? "ready"
            : "not detected"
    );


    // --------------------------------------------------------
    // Wi-Fi
    // --------------------------------------------------------

    connectWifi();


    // --------------------------------------------------------
    // Time
    // --------------------------------------------------------

    if (WiFi.status() == WL_CONNECTED) {

        MqttTime::sync(
            10000
        );
    }


    // --------------------------------------------------------
    // MQTT
    // --------------------------------------------------------

    mqttClient.begin(
        NetworkConfig::MQTT_BROKER,
        NetworkConfig::MQTT_PORT,
        wifiClient
    );

    connectMqtt();


    Serial.println(
        "[SYSTEM] Wearable running."
    );
}


// ============================================================
// LOOP
// ============================================================

void loop() {

    if (
        WiFi.status()
        != WL_CONNECTED
    ) {
        connectWifi();
    }

    retryNtpIfDue();


    if (!mqttClient.connected()) {
        connectMqtt();
    }


    mqttClient.loop();

    dwm1000Ranging.loop();

    if (oxygenReady) {
        if (oxygenDriver.update()) {
            if (oxygenDriver.hasNewData()) {
                latestOxygen =
                    oxygenDriver.getData();

                hasOxygen = true;

                oxygenDriver.clearNewData();
            }
        } else if (
            !oxygenDriver.getData().valid
            && !oxygenDriver.isWaitingForResponse()
        ) {
            latestOxygen =
                oxygenDriver.getData();

            hasOxygen = false;
        }
    }

    unsigned long now =
        millis();

    if (
        now - lastDwm1000CheckMs
        >= DWM1000_CHECK_INTERVAL_MS
    ) {
        lastDwm1000CheckMs =
            now;

        dwm1000Ready =
            dwm1000Ranging.isReady();
    }


    // IMU 5 Hz
    if (
        now - lastImuMs
        >= IMU_INTERVAL_MS
    ) {

        lastImuMs =
            now;

        publishImu();
    }


    // O2 1 Hz
    if (
        now - lastO2Ms
        >= O2_INTERVAL_MS
    ) {

        lastO2Ms =
            now;

        publishOxygen();
    }


    // status 10 s
    if (
        now - lastStatusMs
        >= STATUS_INTERVAL_MS
    ) {

        lastStatusMs =
            now;

        publishStatus();
    }


    // UWB ranging 5 Hz
    if (
        now - lastUwbPublishMs
        >= UWB_PUBLISH_INTERVAL_MS
    ) {

        lastUwbPublishMs =
            now;

        publishRanging();
    }


    delay(1);
}
