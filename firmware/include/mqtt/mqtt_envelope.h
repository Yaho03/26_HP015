#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>

enum class SourceMode : uint8_t {
    LIVE,
    SIMULATION
};

enum class MessageStatus : uint8_t {
    COMPLETE,
    PARTIAL,
    DEGRADED
};

enum class SensorQuality : uint8_t {
    VALID,
    WARMING_UP,
    UNCALIBRATED,
    ERROR,
    NOT_CONNECTED
};

class MqttEnvelopeBuilder {
public:
    MqttEnvelopeBuilder(
        const String& nodeId,
        const String& bootId,
        SourceMode sourceMode = SourceMode::LIVE
    );

    /*
     * Envelope의 공통 필드를 생성하고
     * data 객체를 반환한다.
     *
     * 반환된 JsonObject에 토픽별 센서값을 넣으면 된다.
     */
    JsonObject begin(
        JsonDocument& document,
        const String& messageId,
        const String& sampledAt,
        const String& publishedAt,
        MessageStatus messageStatus,
        bool timeSynced
    );

    void addSensorQuality(
        JsonDocument& document,
        const String& sensorId,
        SensorQuality quality
    );

    uint32_t currentSequence() const;
    void resetSequence();

private:
    static const char* sourceModeToString(SourceMode mode);
    static const char* messageStatusToString(MessageStatus status);
    static const char* sensorQualityToString(SensorQuality quality);

    String nodeId_;
    String bootId_;
    SourceMode sourceMode_;

    uint32_t sequence_ = 0;
};