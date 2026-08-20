#include "mqtt/mqtt_time.h"

#include <time.h>
#include <sys/time.h>

namespace MqttTime {

namespace {

constexpr time_t MIN_VALID_EPOCH = 1700000000;  // 2023년 이후면 정상으로 판단

}  // namespace

bool isSynced() {
    struct timeval tv;

    if (gettimeofday(&tv, nullptr) != 0) {
        return false;
    }

    return tv.tv_sec >= MIN_VALID_EPOCH;
}

bool sync(const unsigned long timeoutMs) {
    Serial.println("[TIME] Starting NTP synchronization.");

    // UTC 기준
    configTime(
        0,
        0,
        "pool.ntp.org",
        "time.google.com"
    );

    const unsigned long startMs = millis();

    while (!isSynced()) {
        if (millis() - startMs >= timeoutMs) {
            Serial.println("[TIME] NTP synchronization timeout.");
            return false;
        }

        delay(250);
    }

    Serial.println("[TIME] NTP synchronization successful.");
    return true;
}

uint64_t nowMs() {
    struct timeval tv;

    if (gettimeofday(&tv, nullptr) != 0) {
        return 0;
    }

    return
        static_cast<uint64_t>(tv.tv_sec) * 1000ULL
        + static_cast<uint64_t>(tv.tv_usec / 1000);
}

String nowIso8601Utc() {
    struct timeval tv;

    if (gettimeofday(&tv, nullptr) != 0) {
        return "";
    }

    struct tm utcTime;
    gmtime_r(&tv.tv_sec, &utcTime);

    char buffer[32];

    snprintf(
        buffer,
        sizeof(buffer),
        "%04d-%02d-%02dT%02d:%02d:%02d.%03ldZ",
        utcTime.tm_year + 1900,
        utcTime.tm_mon + 1,
        utcTime.tm_mday,
        utcTime.tm_hour,
        utcTime.tm_min,
        utcTime.tm_sec,
        tv.tv_usec / 1000
    );

    return String(buffer);
}

}  // namespace MqttTime