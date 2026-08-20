#include "mqtt/ulid.h"

#include <esp_system.h>

#include "mqtt/mqtt_time.h"

namespace Ulid {

namespace {

constexpr char CROCKFORD_BASE32[] =
    "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

void fillRandomBytes(uint8_t* buffer, const size_t length) {
    size_t index = 0;

    while (index < length) {
        const uint32_t randomValue = esp_random();

        for (
            uint8_t byteIndex = 0;
            byteIndex < 4 && index < length;
            ++byteIndex
        ) {
            buffer[index++] =
                static_cast<uint8_t>(
                    randomValue >> (byteIndex * 8)
                );
        }
    }
}

String encodeUlid(const uint8_t data[16]) {
    /*
     * ULID:
     * 128 bit 데이터를 Crockford Base32 26자로 표현.
     * 26 × 5 = 130 bit이므로 맨 앞 2bit는 0으로 처리한다.
     */

    char output[27];

    for (uint8_t charIndex = 0; charIndex < 26; ++charIndex) {
        uint8_t value = 0;

        for (uint8_t bit = 0; bit < 5; ++bit) {
            value <<= 1;

            const int streamPosition =
                charIndex * 5 + bit;

            // ULID 130bit 표현의 앞 2bit는 항상 0
            if (streamPosition < 2) {
                continue;
            }

            const int dataBitPosition =
                streamPosition - 2;

            const int byteIndex =
                dataBitPosition / 8;

            const int bitIndex =
                7 - (dataBitPosition % 8);

            const uint8_t bitValue =
                (data[byteIndex] >> bitIndex) & 0x01;

            value |= bitValue;
        }

        output[charIndex] =
            CROCKFORD_BASE32[value];
    }

    output[26] = '\0';

    return String(output);
}

}  // namespace

String generate() {
    return generate(MqttTime::nowMs());
}

String generate(const uint64_t timestampMs) {
    uint8_t data[16] = {};

    /*
     * ULID 앞 48bit = timestamp(ms)
     */
    const uint64_t timestamp =
        timestampMs & 0x0000FFFFFFFFFFFFULL;

    data[0] = (timestamp >> 40) & 0xFF;
    data[1] = (timestamp >> 32) & 0xFF;
    data[2] = (timestamp >> 24) & 0xFF;
    data[3] = (timestamp >> 16) & 0xFF;
    data[4] = (timestamp >> 8) & 0xFF;
    data[5] = timestamp & 0xFF;

    /*
     * 뒤 80bit = ESP32 hardware RNG
     */
    fillRandomBytes(
        &data[6],
        10
    );

    return encodeUlid(data);
}

}  // namespace Ulid