#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <MQTT.h>
#include <ArduinoJson.h>
#include <Adafruit_MLX90640.h>

#include "config/network_config.h"
#include "mqtt/mqtt_time.h"
#include "mqtt/ulid.h"


// ============================================================
// Configuration
// ============================================================

constexpr char NODE_ID[] =
    "thermal-01";

constexpr uint8_t SDA_PIN = 21;
constexpr uint8_t SCL_PIN = 22;

constexpr unsigned long THERMAL_INTERVAL_MS =
    500;

constexpr unsigned long STATUS_INTERVAL_MS =
    10000;

constexpr unsigned long NTP_RETRY_INITIAL_MS = 5000;
constexpr unsigned long NTP_RETRY_MAX_MS = 60000;
constexpr unsigned long NTP_SYNC_TIMEOUT_MS = 5000;


// ============================================================
// Network
// ============================================================

WiFiClient wifiClient;

MQTTClient mqttClient(1024);


// ============================================================
// MLX90640
// ============================================================

Adafruit_MLX90640 mlx;

float frame[32 * 24];

bool thermalReady = false;


// ============================================================
// Timing
// ============================================================

unsigned long lastThermalMs = 0;
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

    if (
        WiFi.status()
        != WL_CONNECTED
    ) {
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

    Serial.print(
        "[WiFi] Connecting to "
    );

    Serial.println(
        NetworkConfig::WIFI_SSID
    );


    WiFi.mode(
        WIFI_STA
    );


    WiFi.begin(
        NetworkConfig::WIFI_SSID,
        NetworkConfig::WIFI_PASSWORD
    );


    unsigned long startMs =
        millis();


    while (
        WiFi.status()
        != WL_CONNECTED
    ) {

        delay(500);
        Serial.print(".");

        if (
            millis() - startMs
            >= 20000
        ) {

            Serial.println();
            Serial.println(
                "[WiFi] Connection timeout."
            );

            return;
        }
    }


    Serial.println();

    Serial.println(
        "[WiFi] Connected."
    );

    Serial.print(
        "[WiFi] IP: "
    );

    Serial.println(
        WiFi.localIP()
    );
}


// ============================================================
// MQTT
// ============================================================

void connectMqtt() {

    if (mqttClient.connected()) {
        return;
    }

    if (
        WiFi.status()
        != WL_CONNECTED
    ) {
        return;
    }


    String clientId =
        String(NODE_ID)
        + "-"
        + String(
            static_cast<uint32_t>(
                ESP.getEfuseMac()
            ),
            HEX
        );


    Serial.print(
        "[MQTT] Connecting... "
    );


    if (
        mqttClient.connect(
            clientId.c_str()
        )
    ) {

        Serial.println(
            "connected."
        );

    } else {

        Serial.println(
            "failed."
        );
    }
}


// ============================================================
// Thermal frame
// ============================================================

void publishThermal() {

    if (
        !thermalReady ||
        !mqttClient.connected()
    ) {
        return;
    }

    if (
        !ensureTimeSyncedForPublish(
            "THERMAL"
        )
    ) {
        return;
    }


    int result =
        mlx.getFrame(
            frame
        );


    if (result != 0) {

        Serial.print(
            "[MLX90640] Frame error: "
        );

        Serial.println(
            result
        );

        return;
    }


    float minTemp =
        1000.0F;

    float maxTemp =
        -1000.0F;

    float sumTemp =
        0.0F;

    int hottestIndex =
        0;


    for (
        int index = 0;
        index < 768;
        ++index
    ) {

        float temperature =
            frame[index];


        if (
            isnan(temperature) ||
            isinf(temperature)
        ) {
            continue;
        }


        sumTemp +=
            temperature;


        if (
            temperature
            < minTemp
        ) {

            minTemp =
                temperature;
        }


        if (
            temperature
            > maxTemp
        ) {

            maxTemp =
                temperature;

            hottestIndex =
                index;
        }
    }


    float avgTemp =
        sumTemp / 768.0F;


    int hotspotX =
        hottestIndex % 32;

    int hotspotY =
        hottestIndex / 32;


    // --------------------------------------------------------
    // JSON
    // --------------------------------------------------------

    JsonDocument document;


    document["node_id"] =
        NODE_ID;

    document["message_id"] =
        Ulid::generate();

    document["sampled_at"] =
        MqttTime::nowIso8601Utc();


    JsonObject data =
        document["data"].to<JsonObject>();


    data["min_temp_c"] =
        minTemp;

    data["max_temp_c"] =
        maxTemp;

    data["avg_temp_c"] =
        avgTemp;

    data["hotspot_x"] =
        hotspotX;

    data["hotspot_y"] =
        hotspotY;


    String payload;

    serializeJson(
        document,
        payload
    );


    bool ok =
        mqttClient.publish(
            "thermal/thermal-01/summary",
            payload,
            false,
            1
        );


    if (ok) {

        Serial.print(
            "[THERMAL MQTT] "
        );

        Serial.println(
            payload
        );

    } else {

        Serial.println(
            "[MQTT] Thermal publish failed."
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

    if (
        !ensureTimeSyncedForPublish(
            "THERMAL STATUS"
        )
    ) {
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

    data["mlx90640_ready"] =
        thermalReady;


    String payload;

    serializeJson(
        document,
        payload
    );


    mqttClient.publish(
        "thermal/thermal-01/status",
        payload,
        false,
        1
    );
}


// ============================================================
// SETUP
// ============================================================

void setup() {

    Serial.begin(
        115200
    );

    delay(
        1500
    );


    Serial.println();

    Serial.println(
        "[SYSTEM] Thermal MQTT node"
    );


    // --------------------------------------------------------
    // I2C
    // --------------------------------------------------------

    Wire.begin(
        SDA_PIN,
        SCL_PIN
    );


    // MLX90640은 데이터량이 많으므로 400 kHz
    Wire.setClock(
        400000
    );


    // --------------------------------------------------------
    // MLX90640
    // --------------------------------------------------------

    Serial.println(
        "[MLX90640] Initializing..."
    );


    thermalReady =
        mlx.begin(
            MLX90640_I2CADDR_DEFAULT,
            &Wire
        );


    if (thermalReady) {

        Serial.println(
            "[MLX90640] Ready."
        );


        mlx.setMode(
            MLX90640_CHESS
        );


        mlx.setResolution(
            MLX90640_ADC_18BIT
        );


        mlx.setRefreshRate(
            MLX90640_4_HZ
        );

    } else {

        Serial.println(
            "[MLX90640] Not detected."
        );
    }


    // --------------------------------------------------------
    // Wi-Fi
    // --------------------------------------------------------

    connectWifi();


    // --------------------------------------------------------
    // NTP
    // --------------------------------------------------------

    if (
        WiFi.status()
        == WL_CONNECTED
    ) {

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
        "[SYSTEM] Thermal node running."
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


    if (
        !mqttClient.connected()
    ) {

        connectMqtt();
    }


    mqttClient.loop();


    unsigned long now =
        millis();


    // --------------------------------------------------------
    // Thermal
    // --------------------------------------------------------

    if (
        now - lastThermalMs
        >= THERMAL_INTERVAL_MS
    ) {

        lastThermalMs =
            now;

        publishThermal();
    }


    // --------------------------------------------------------
    // Status
    // --------------------------------------------------------

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
