#pragma once

#if __has_include("network_config.local.h")
#include "network_config.local.h"
#else

#include <Arduino.h>

namespace NetworkConfig {

constexpr char WIFI_SSID[] = "CHANGE_ME";
constexpr char WIFI_PASSWORD[] = "CHANGE_ME";

constexpr char MQTT_BROKER[] = "192.168.0.10";
constexpr uint16_t MQTT_PORT = 1883;
constexpr char MQTT_USERNAME[] = "";
constexpr char MQTT_PASSWORD[] = "";

}  // namespace NetworkConfig

#endif
