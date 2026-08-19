#pragma once

#include <Arduino.h>

namespace MqttTopics {

String sensorGas(const String& nodeId);
String sensorEnv(const String& nodeId);
String sensorStatus(const String& nodeId);

String wearableLocation(const String& nodeId);
String wearableImu(const String& nodeId);
String wearableVital(const String& nodeId);

String connection(const String& nodeId);

}  // namespace MqttTopics