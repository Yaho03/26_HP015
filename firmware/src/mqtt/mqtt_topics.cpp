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

String connection(const String& nodeId) {
    return "nodes/" + nodeId + "/connection";
}

}  // namespace MqttTopics