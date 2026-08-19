#include "mqtt/mqtt_envelope.h"

MqttEnvelopeBuilder::MqttEnvelopeBuilder(
    const String& nodeId,
    const String& bootId,
    const SourceMode sourceMode
)
    : nodeId_(nodeId),
      bootId_(bootId),
      sourceMode_(sourceMode) {
}

JsonObject MqttEnvelopeBuilder::begin(
    JsonDocument& document,
    const String& messageId,
    const String& sampledAt,
    const String& publishedAt,
    const MessageStatus messageStatus,
    const bool timeSynced
) {
    document.clear();

    document["schema_version"] = "1.1";
    document["message_id"] = messageId;
    document["node_id"] = nodeId_;
    document["boot_id"] = bootId_;

    /*
     * 첫 메시지는 sequence 0을 사용하고,
     * Envelope 생성 후 다음 번호로 증가한다.
     */
    document["sequence"] = sequence_++;

    document["sampled_at"] = sampledAt;
    document["published_at"] = publishedAt;
    document["source_mode"] =
        sourceModeToString(sourceMode_);

    if (sourceMode_ == SourceMode::LIVE) {
        document["simulation"] = nullptr;
    } else {
        JsonObject simulation =
            document["simulation"].to<JsonObject>();

        /*
         * 실제 simulation 메타데이터는
         * 데이터 주입 기능 구현 시 설정한다.
         */
        simulation["run_id"] = "";
        simulation["scenario_id"] = "";
    }

    JsonObject quality =
        document["quality"].to<JsonObject>();

    quality["message_status"] =
        messageStatusToString(messageStatus);

    quality["time_synced"] = timeSynced;

    quality["sensors"].to<JsonObject>();

    return document["data"].to<JsonObject>();
}

void MqttEnvelopeBuilder::addSensorQuality(
    JsonDocument& document,
    const String& sensorId,
    const SensorQuality quality
) {
    JsonObject sensors =
        document["quality"]["sensors"].as<JsonObject>();

    if (sensors.isNull()) {
        sensors =
            document["quality"]["sensors"].to<JsonObject>();
    }

    sensors[sensorId] =
        sensorQualityToString(quality);
}

uint32_t MqttEnvelopeBuilder::currentSequence() const {
    return sequence_;
}

void MqttEnvelopeBuilder::resetSequence() {
    sequence_ = 0;
}

const char* MqttEnvelopeBuilder::sourceModeToString(
    const SourceMode mode
) {
    switch (mode) {
        case SourceMode::LIVE:
            return "live";

        case SourceMode::SIMULATION:
            return "simulation";

        default:
            return "live";
    }
}

const char* MqttEnvelopeBuilder::messageStatusToString(
    const MessageStatus status
) {
    switch (status) {
        case MessageStatus::COMPLETE:
            return "complete";

        case MessageStatus::PARTIAL:
            return "partial";

        case MessageStatus::DEGRADED:
            return "degraded";

        default:
            return "degraded";
    }
}

const char* MqttEnvelopeBuilder::sensorQualityToString(
    const SensorQuality quality
) {
    switch (quality) {
        case SensorQuality::VALID:
            return "valid";

        case SensorQuality::WARMING_UP:
            return "warming_up";

        case SensorQuality::UNCALIBRATED:
            return "uncalibrated";

        case SensorQuality::ERROR:
            return "error";

        case SensorQuality::NOT_CONNECTED:
            return "not_connected";

        default:
            return "error";
    }
}