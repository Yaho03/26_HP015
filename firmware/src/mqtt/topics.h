#pragma once

// MQTT 토픽 패턴 (이슈 #44, 04_DATA_CONTRACT.md 3.1).
// {node_id} 자리는 런타임에 노드 ID로 치환한다.

namespace hp015::topics {

constexpr const char* SENSORS_GAS       = "sensors/%s/gas";
constexpr const char* SENSORS_ENV       = "sensors/%s/env";
constexpr const char* SENSORS_STATUS    = "sensors/%s/status";
constexpr const char* WEARABLE_LOCATION = "wearable/%s/location";
constexpr const char* WEARABLE_IMU      = "wearable/%s/imu";
constexpr const char* WEARABLE_VITAL    = "wearable/%s/vital";
constexpr const char* NODE_CONNECTION   = "nodes/%s/connection";

constexpr const char* ALERTS_EVENTS     = "alerts/events/%s";
constexpr const char* ALERTS_STATE      = "alerts/state/%s/%s";

constexpr const char* SCHEMA_VERSION    = "1.1";

}  // namespace hp015::topics
