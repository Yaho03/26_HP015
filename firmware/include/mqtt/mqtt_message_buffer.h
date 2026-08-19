#pragma once

#include <Arduino.h>

struct BufferedMqttMessage {
    String topic;
    String payload;
    uint8_t qos = 0;
    bool retain = false;
};

class MqttMessageBuffer {
public:
    static constexpr size_t MAX_MESSAGES = 100;

    bool push(
        const String& topic,
        const String& payload,
        uint8_t qos,
        bool retain
    );

    bool pop(BufferedMqttMessage& message);

    const BufferedMqttMessage* peek() const;

    size_t size() const;
    bool empty() const;
    bool full() const;

    void clear();

private:
    BufferedMqttMessage messages_[MAX_MESSAGES];

    size_t head_ = 0;
    size_t tail_ = 0;
    size_t count_ = 0;
};