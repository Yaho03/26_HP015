#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <MQTT.h>
#include <ArduinoJson.h>

#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>

#include "config/network_config.h"
#include "drivers/sen0322_driver.h"
#include "mqtt/mqtt_time.h"
#include "mqtt/ulid.h"

// ============================================================
// Configuration
// ============================================================

constexpr char NODE_ID[] = "wearable-01";

constexpr uint8_t SDA_PIN = 21;
constexpr uint8_t SCL_PIN = 22;

// SEN0322
#define OXYGEN_I2C_ADDRESS ADDRESS_3

constexpr uint8_t OXYGEN_COLLECT_NUMBER = 10;

constexpr unsigned long IMU_INTERVAL_MS = 200;     // 5 Hz
constexpr unsigned long O2_INTERVAL_MS = 1000;    // 1 Hz
constexpr unsigned long STATUS_INTERVAL_MS = 10000;

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

bool mpuReady = false;
bool oxygenReady = false;

Sen0322Data latestOxygen;
bool hasOxygen = false;


// ============================================================
// Timing
// ============================================================

unsigned long lastImuMs = 0;
unsigned long lastO2Ms = 0;
unsigned long lastStatusMs = 0;

unsigned long lastNtpAttemptMs = 0;
unsigned long ntpRetryIntervalMs = NTP_RETRY_INITIAL_MS;


// ============================================================
// Time
// ============================================================

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

    if (mqttClient.connect(clientId.c_str())) {

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
            "wearable/wearable-01/imu",
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
            "wearable/wearable-01/vital",
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


    String payload;

    serializeJson(
        document,
        payload
    );

    mqttClient.publish(
        "wearable/wearable-01/status",
        payload,
        false,
        1
    );
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


    delay(1);
}
