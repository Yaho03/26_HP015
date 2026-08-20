#pragma once

#include <Arduino.h>

namespace NetworkConfig {

constexpr char WIFI_SSID[] = "YOUR_WIFI_SSID";
constexpr char WIFI_PASSWORD[] = "YOUR_WIFI_PASSWORD";

constexpr char MQTT_BROKER[] = "YOUR_BACKEND_OR_BROKER_IP";
constexpr uint16_t MQTT_PORT = 1883;
constexpr char MQTT_USERNAME[] = "hp015";
constexpr char MQTT_PASSWORD[] = "hp015_dev_pw";

}  // namespace NetworkConfig
