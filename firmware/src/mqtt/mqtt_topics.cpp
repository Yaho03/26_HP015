#include "mqtt/mqtt_topics.h"

namespace MqttTopics {

String sensorGas(const String& nodeId) {
    return "sensors/" + nodeId + "/gas";
}

String sensorEnv(const String& nodeId) {
    return "sensors/" + nodeId + "/env";
}

String sensorStatus(const String& nodeId) {
    return "sensors/" + nodeId + "/status";
}

String wearableLocation(const String& nodeId) {
    return "wearable/" + nodeId + "/location";
}

String wearableImu(const String& nodeId) {
    return "wearable/" + nodeId + "/imu";
}

String wearableVital(const String& nodeId) {
    return "wearable/" + nodeId + "/vital";
}

// UWB 앵커 거리 (04_DATA_CONTRACT.md 3.1, 백엔드가 wearable/+/ranging 로 구독).
String wearableRanging(const String& nodeId) {
    return "wearable/" + nodeId + "/ranging";
}

String connection(const String& nodeId) {
    return "nodes/" + nodeId + "/connection";
}

}  // namespace MqttTopics