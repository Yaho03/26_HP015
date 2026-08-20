#include "mqtt/mqtt_message_buffer.h"

bool MqttMessageBuffer::push(
    const String& topic,
    const String& payload,
    const uint8_t qos,
    const bool retain
) {
    /*
     * 버퍼가 가득 찬 경우:
     * 가장 오래된 메시지를 버리고 새 메시지를 저장한다.
     */
    if (full()) {
        head_ = (head_ + 1) % MAX_MESSAGES;
        --count_;
    }

    messages_[tail_].topic = topic;
    messages_[tail_].payload = payload;
    messages_[tail_].qos = qos;
    messages_[tail_].retain = retain;

    tail_ = (tail_ + 1) % MAX_MESSAGES;
    ++count_;

    return true;
}

bool MqttMessageBuffer::pop(
    BufferedMqttMessage& message
) {
    if (empty()) {
        return false;
    }

    message = messages_[head_];

    messages_[head_].topic = "";
    messages_[head_].payload = "";
    messages_[head_].qos = 0;
    messages_[head_].retain = false;

    head_ = (head_ + 1) % MAX_MESSAGES;
    --count_;

    return true;
}

const BufferedMqttMessage*
MqttMessageBuffer::peek() const {
    if (empty()) {
        return nullptr;
    }

    return &messages_[head_];
}

size_t MqttMessageBuffer::size() const {
    return count_;
}

bool MqttMessageBuffer::empty() const {
    return count_ == 0;
}

bool MqttMessageBuffer::full() const {
    return count_ >= MAX_MESSAGES;
}

void MqttMessageBuffer::clear() {
    for (size_t index = 0; index < MAX_MESSAGES; ++index) {
        messages_[index].topic = "";
        messages_[index].payload = "";
        messages_[index].qos = 0;
        messages_[index].retain = false;
    }

    head_ = 0;
    tail_ = 0;
    count_ = 0;
}