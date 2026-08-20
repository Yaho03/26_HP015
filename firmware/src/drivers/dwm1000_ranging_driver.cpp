#include "drivers/dwm1000_ranging_driver.h"

#include <DW1000Ng.hpp>
#include <SPI.h>
#include <math.h>
#include <string.h>

Dwm1000RangingDriver* Dwm1000RangingDriver::active_ = nullptr;

constexpr uint16_t Dwm1000RangingDriver::ANCHOR_SHORT_ADDRESSES[
    Dwm1000RangingDriver::MAX_ANCHOR_RANGES
];

Dwm1000RangingDriver::Dwm1000RangingDriver(
    const Dwm1000Role role,
    const char* eui,
    const uint16_t shortAddress,
    const int8_t sckPin,
    const int8_t misoPin,
    const int8_t mosiPin,
    const int8_t csPin,
    const int8_t rstPin,
    const int8_t irqPin
)
    : role_(role),
      eui_(eui),
      shortAddress_(shortAddress),
      sckPin_(sckPin),
      misoPin_(misoPin),
      mosiPin_(mosiPin),
      csPin_(csPin),
      rstPin_(rstPin),
      irqPin_(irqPin) {
}

bool Dwm1000RangingDriver::begin() {
    active_ =
        this;

    SPI.begin(
        sckPin_,
        misoPin_,
        mosiPin_,
        csPin_
    );

    uwb_.setCallbacks(
        onTxDone,
        onRxDone
    );

    ready_ =
        uwb_.begin(
            csPin_,
            irqPin_,
            rstPin_,
            SPI
        );

    if (ready_) {
        uwb_.configure(
            5,
            9,
            128,
            1
        );
        uwb_.setAntennaDelay(
            ANTENNA_DELAY
        );

        attachInterrupt(
            digitalPinToInterrupt(irqPin_),
            onIrq,
            RISING
        );

        if (role_ == Dwm1000Role::ANCHOR_NODE) {
            anchorState_ =
                AnchorState::WAIT_POLL;
            uwb_.startReceive();
        } else {
            tagState_ =
                TagState::IDLE;
            lastRangeMs_ =
                millis() - RANGE_PERIOD_MS;
        }
    }

    char msg[96] = {};
    DW1000Ng::getPrintableDeviceIdentifier(msg);
    deviceIdentifier_ =
        msg;

    Serial.print("[DWM1000] role=");
    Serial.print(roleName());
    Serial.print(", eui=");
    Serial.print(eui_);
    Serial.print(", short=");
    Serial.print(shortAddress_);
    Serial.print(", device=");
    Serial.print(deviceIdentifier_);
    Serial.print(", ready=");
    Serial.println(
        ready_
            ? "true"
            : "false"
    );

    return ready_;
}

void Dwm1000RangingDriver::loop() {
    if (!ready_) {
        return;
    }

    processIrq();

    if (txComplete_) {
        txComplete_ =
            false;
        processTxDone();
    }

    if (rxComplete_) {
        rxComplete_ =
            false;
        processRxDone();
    }

    const unsigned long nowMs =
        millis();

    if (
        role_ == Dwm1000Role::TAG_NODE
        && tagState_ == TagState::IDLE
        && nowMs - lastRangeMs_ >= RANGE_PERIOD_MS
    ) {
        lastRangeMs_ =
            nowMs;
        sendTagPoll();
    }

    if (
        role_ == Dwm1000Role::TAG_NODE
        && (
            tagState_ == TagState::WAIT_RESP
            || tagState_ == TagState::WAIT_RESULT
        )
        && nowMs - stateStartedMs_ > RANGE_TIMEOUT_MS
    ) {
        Serial.println("[DWM1000] tag ranging timeout");
        tagState_ =
            TagState::IDLE;
        currentAnchorIndex_ =
            (currentAnchorIndex_ + 1) % MAX_ANCHOR_RANGES;
        uwb_.startReceive();
    }

    if (
        role_ == Dwm1000Role::ANCHOR_NODE
        && anchorState_ == AnchorState::WAIT_FINAL
        && nowMs - stateStartedMs_ > RANGE_TIMEOUT_MS
    ) {
        Serial.println("[DWM1000] anchor FINAL timeout");
        anchorState_ =
            AnchorState::WAIT_POLL;
        uwb_.startReceive();
    }
}

bool Dwm1000RangingDriver::isReady() const {
    return ready_;
}

bool Dwm1000RangingDriver::hasNewRange() const {
    return hasNewRange_;
}

void Dwm1000RangingDriver::clearNewRangeFlag() {
    hasNewRange_ =
        false;
}

size_t Dwm1000RangingDriver::copyFreshRanges(
    Dwm1000Range* out,
    const size_t maxCount,
    const unsigned long maxAgeMs
) const {
    const unsigned long nowMs =
        millis();

    size_t count = 0;

    for (const Dwm1000Range& range : ranges_) {
        if (
            !range.valid
            || range.anchorId == nullptr
            || nowMs - range.updatedMs > maxAgeMs
        ) {
            continue;
        }

        if (count >= maxCount) {
            break;
        }

        out[count++] =
            range;
    }

    return count;
}

const String& Dwm1000RangingDriver::deviceIdentifier() const {
    return deviceIdentifier_;
}

const String& Dwm1000RangingDriver::eui() const {
    return eui_;
}

const char* Dwm1000RangingDriver::roleName() const {
    return role_ == Dwm1000Role::ANCHOR_NODE
        ? "anchor"
        : "tag";
}

void Dwm1000RangingDriver::onTxDone() {
    if (active_ != nullptr) {
        active_->txComplete_ =
            true;
    }
}

void Dwm1000RangingDriver::onRxDone() {
    if (active_ != nullptr) {
        active_->rxComplete_ =
            true;
    }
}

void Dwm1000RangingDriver::onIrq() {
    if (active_ != nullptr) {
        active_->irqPending_ =
            true;
    }
}

void Dwm1000RangingDriver::processIrq() {
    if (
        irqPending_
        || digitalRead(irqPin_)
    ) {
        irqPending_ =
            false;
        uwb_.onIRQ();
    }
}

void Dwm1000RangingDriver::processTxDone() {
    if (
        role_ == Dwm1000Role::TAG_NODE
        && tagState_ == TagState::WAIT_POLL_TX
    ) {
        pollTxTs_ =
            uwb_.getTransmitTimestamp();
        tagState_ =
            TagState::WAIT_RESP;
        stateStartedMs_ =
            millis();
        uwb_.startReceive();
    }
}

void Dwm1000RangingDriver::processRxDone() {
    rxLength_ =
        0;

    const uint64_t rxTs =
        uwb_.getReceiveTimestamp();

    if (
        !uwb_.readReceivedData(
            rxBuffer_,
            rxLength_
        )
    ) {
        return;
    }

    if (role_ == Dwm1000Role::TAG_NODE) {
        processTagRx(
            rxTs,
            rxBuffer_,
            rxLength_
        );
    } else {
        processAnchorRx(
            rxTs,
            rxBuffer_,
            rxLength_
        );
    }
}

void Dwm1000RangingDriver::sendTagPoll() {
    currentTargetAnchor_ =
        ANCHOR_SHORT_ADDRESSES[currentAnchorIndex_];
    currentSeq_ =
        ++seqCounter_;

    uint8_t frame[HEADER_LEN] = {};
    makeHeader(
        frame,
        MSG_POLL,
        currentSeq_,
        shortAddress_,
        currentTargetAnchor_
    );

    if (
        uwb_.transmit(
            frame,
            sizeof(frame)
        )
    ) {
        tagState_ =
            TagState::WAIT_POLL_TX;
        stateStartedMs_ =
            millis();
    } else {
        Serial.println("[DWM1000] POLL TX failed");
        tagState_ =
            TagState::IDLE;
    }
}

void Dwm1000RangingDriver::processTagRx(
    const uint64_t rxTs,
    const uint8_t* frame,
    const uint16_t len
) {
    if (
        !validHeader(
            frame,
            len,
            shortAddress_
        )
    ) {
        return;
    }

    const uint8_t type =
        frame[2];
    const uint8_t seq =
        frame[3];
    const uint16_t src =
        readU16(frame + 4);

    if (
        tagState_ == TagState::WAIT_RESP
        && type == MSG_RESP
        && seq == currentSeq_
        && src == currentTargetAnchor_
        && len >= HEADER_LEN + 10
    ) {
        respRxTs_ =
            rxTs;

        const uint64_t finalTxTs =
            uwb_.calculateDelayedTransmitTimestamp(
                respRxTs_,
                uusToUwbTicks(FINAL_DELAY_UUS)
            );

        uint8_t finalFrame[HEADER_LEN + 15] = {};
        makeHeader(
            finalFrame,
            MSG_FINAL,
            currentSeq_,
            shortAddress_,
            currentTargetAnchor_
        );
        writeTs40(finalFrame + HEADER_LEN, pollTxTs_);
        writeTs40(finalFrame + HEADER_LEN + 5, respRxTs_);
        writeTs40(finalFrame + HEADER_LEN + 10, finalTxTs);

        if (
            uwb_.transmitDelayedAt(
                finalFrame,
                sizeof(finalFrame),
                finalTxTs
            )
        ) {
            tagState_ =
                TagState::WAIT_RESULT;
            stateStartedMs_ =
                millis();
            uwb_.startReceive();
        } else {
            Serial.println("[DWM1000] FINAL delayed TX failed");
            tagState_ =
                TagState::IDLE;
            uwb_.startReceive();
        }
        return;
    }

    if (
        tagState_ == TagState::WAIT_RESULT
        && type == MSG_RESULT
        && seq == currentSeq_
        && src == currentTargetAnchor_
        && len >= HEADER_LEN + 6
    ) {
        const int32_t distanceMm =
            readI32(frame + HEADER_LEN);
        const int16_t rxPowerTenths =
            readI16(frame + HEADER_LEN + 4);

        storeRange(
            currentTargetAnchor_,
            static_cast<float>(distanceMm) / 1000.0F,
            static_cast<float>(rxPowerTenths) / 10.0F
        );

        currentAnchorIndex_ =
            (currentAnchorIndex_ + 1) % MAX_ANCHOR_RANGES;
        tagState_ =
            TagState::IDLE;
    }
}

void Dwm1000RangingDriver::processAnchorRx(
    const uint64_t rxTs,
    const uint8_t* frame,
    const uint16_t len
) {
    if (
        !validHeader(
            frame,
            len,
            shortAddress_
        )
    ) {
        return;
    }

    const uint8_t type =
        frame[2];
    const uint8_t seq =
        frame[3];
    const uint16_t src =
        readU16(frame + 4);

    if (
        type == MSG_POLL
        && len >= HEADER_LEN
    ) {
        savedSeq_ =
            seq;
        savedTagShortAddress_ =
            src;
        savedPollRxTs_ =
            rxTs;
        savedRespTxTs_ =
            uwb_.calculateDelayedTransmitTimestamp(
                savedPollRxTs_,
                uusToUwbTicks(RESP_DELAY_UUS)
            );

        uint8_t respFrame[HEADER_LEN + 10] = {};
        makeHeader(
            respFrame,
            MSG_RESP,
            savedSeq_,
            shortAddress_,
            savedTagShortAddress_
        );
        writeTs40(respFrame + HEADER_LEN, savedPollRxTs_);
        writeTs40(respFrame + HEADER_LEN + 5, savedRespTxTs_);

        if (
            uwb_.transmitDelayedAt(
                respFrame,
                sizeof(respFrame),
                savedRespTxTs_
            )
        ) {
            anchorState_ =
                AnchorState::WAIT_FINAL;
            stateStartedMs_ =
                millis();
            uwb_.startReceive();
        } else {
            Serial.println("[DWM1000] RESP delayed TX failed");
            anchorState_ =
                AnchorState::WAIT_POLL;
            uwb_.startReceive();
        }
        return;
    }

    if (
        anchorState_ == AnchorState::WAIT_FINAL
        && type == MSG_FINAL
        && seq == savedSeq_
        && src == savedTagShortAddress_
        && len >= HEADER_LEN + 15
    ) {
        const uint64_t finalRxTs =
            rxTs;
        const uint64_t initiatorPollTxTs =
            readTs40(frame + HEADER_LEN);
        const uint64_t initiatorRespRxTs =
            readTs40(frame + HEADER_LEN + 5);
        const uint64_t initiatorFinalTxTs =
            readTs40(frame + HEADER_LEN + 10);

        const double distanceM =
            calculateDsTwrDistanceM(
                initiatorPollTxTs,
                savedPollRxTs_,
                savedRespTxTs_,
                initiatorRespRxTs,
                initiatorFinalTxTs,
                finalRxTs
            );

        Serial.print("[DWM1000] DS-TWR tag=");
        Serial.print(savedTagShortAddress_);
        Serial.print(" distance=");
        Serial.print(distanceM, 3);
        Serial.print("m rx=");
        Serial.print(uwb_.getReceivePower(), 1);
        Serial.println("dBm");

        sendAnchorResult(
            savedSeq_,
            distanceM,
            finalRxTs
        );
    }
}

void Dwm1000RangingDriver::sendAnchorResult(
    const uint8_t seq,
    const double distanceM,
    const uint64_t finalRxTs
) {
    int32_t distanceMm =
        static_cast<int32_t>(
            distanceM * 1000.0
            + (distanceM >= 0.0 ? 0.5 : -0.5)
        );

    if (
        isnan(distanceM)
        || !isfinite(distanceM)
        || distanceM <= 0.0
        || distanceM > 100.0
    ) {
        distanceMm =
            -1;
    }

    const int16_t rxPowerTenths =
        static_cast<int16_t>(
            uwb_.getReceivePower() * 10.0F
        );

    uint8_t resultFrame[HEADER_LEN + 6] = {};
    makeHeader(
        resultFrame,
        MSG_RESULT,
        seq,
        shortAddress_,
        savedTagShortAddress_
    );
    writeI32(resultFrame + HEADER_LEN, distanceMm);
    writeI16(resultFrame + HEADER_LEN + 4, rxPowerTenths);

    const uint64_t resultTxTs =
        uwb_.calculateDelayedTransmitTimestamp(
            finalRxTs,
            uusToUwbTicks(RESULT_DELAY_UUS)
        );

    if (
        !uwb_.transmitDelayedAt(
            resultFrame,
            sizeof(resultFrame),
            resultTxTs
        )
    ) {
        Serial.println("[DWM1000] RESULT delayed TX failed");
    }

    anchorState_ =
        AnchorState::WAIT_POLL;
    uwb_.startReceive();
}

void Dwm1000RangingDriver::storeRange(
    const uint16_t anchorShortAddress,
    const float distanceM,
    const float rxPowerDbm
) {
    const char* anchorId =
        anchorIdForShortAddress(anchorShortAddress);

    if (
        anchorId == nullptr
        || isnan(distanceM)
        || !isfinite(distanceM)
        || distanceM <= 0.0F
        || distanceM > 100.0F
    ) {
        Serial.print("[DWM1000] ignored range short=");
        Serial.print(anchorShortAddress);
        Serial.print(", distance_m=");
        Serial.println(distanceM);
        return;
    }

    Dwm1000Range* slot = nullptr;

    for (Dwm1000Range& range : ranges_) {
        if (
            range.valid
            && range.shortAddress == anchorShortAddress
        ) {
            slot =
                &range;
            break;
        }

        if (slot == nullptr && !range.valid) {
            slot =
                &range;
        }
    }

    if (slot == nullptr) {
        return;
    }

    slot->anchorId =
        anchorId;
    slot->shortAddress =
        anchorShortAddress;
    slot->distanceM =
        distanceM;
    slot->rxPowerDbm =
        rxPowerDbm;
    slot->updatedMs =
        millis();
    slot->valid =
        true;

    hasNewRange_ =
        true;

    Serial.print("[DWM1000] range ");
    Serial.print(anchorId);
    Serial.print("=");
    Serial.print(distanceM, 2);
    Serial.print("m rx=");
    Serial.print(rxPowerDbm, 1);
    Serial.println("dBm");
}

const char* Dwm1000RangingDriver::anchorIdForShortAddress(
    const uint16_t shortAddress
) {
    switch (shortAddress) {
        case 1:
            return "A1";

        case 2:
            return "A2";

        case 3:
            return "A3";

        case 4:
            return "A4";

        default:
            return nullptr;
    }
}

uint32_t Dwm1000RangingDriver::uusToUwbTicks(
    const uint32_t uus
) {
    return uus * UUS_TO_UWB_TIME;
}

uint64_t Dwm1000RangingDriver::diff40(
    const uint64_t later,
    const uint64_t earlier
) {
    return (later - earlier) & UWB40_MASK;
}

void Dwm1000RangingDriver::writeTs40(
    uint8_t* dst,
    uint64_t value
) {
    value &=
        UWB40_MASK;

    for (uint8_t i = 0; i < 5; ++i) {
        dst[i] =
            static_cast<uint8_t>(
                (value >> (8 * i)) & 0xFF
            );
    }
}

uint64_t Dwm1000RangingDriver::readTs40(
    const uint8_t* src
) {
    uint64_t value = 0;

    for (uint8_t i = 0; i < 5; ++i) {
        value |=
            static_cast<uint64_t>(src[i])
            << (8 * i);
    }

    return value & UWB40_MASK;
}

void Dwm1000RangingDriver::writeU16(
    uint8_t* dst,
    const uint16_t value
) {
    dst[0] =
        static_cast<uint8_t>(value & 0xFF);
    dst[1] =
        static_cast<uint8_t>((value >> 8) & 0xFF);
}

uint16_t Dwm1000RangingDriver::readU16(
    const uint8_t* src
) {
    return static_cast<uint16_t>(src[0])
        | (static_cast<uint16_t>(src[1]) << 8);
}

void Dwm1000RangingDriver::writeI32(
    uint8_t* dst,
    const int32_t value
) {
    dst[0] =
        static_cast<uint8_t>(value & 0xFF);
    dst[1] =
        static_cast<uint8_t>((value >> 8) & 0xFF);
    dst[2] =
        static_cast<uint8_t>((value >> 16) & 0xFF);
    dst[3] =
        static_cast<uint8_t>((value >> 24) & 0xFF);
}

int32_t Dwm1000RangingDriver::readI32(
    const uint8_t* src
) {
    return static_cast<int32_t>(
        static_cast<uint32_t>(src[0])
        | (static_cast<uint32_t>(src[1]) << 8)
        | (static_cast<uint32_t>(src[2]) << 16)
        | (static_cast<uint32_t>(src[3]) << 24)
    );
}

void Dwm1000RangingDriver::writeI16(
    uint8_t* dst,
    const int16_t value
) {
    dst[0] =
        static_cast<uint8_t>(value & 0xFF);
    dst[1] =
        static_cast<uint8_t>((value >> 8) & 0xFF);
}

int16_t Dwm1000RangingDriver::readI16(
    const uint8_t* src
) {
    return static_cast<int16_t>(
        static_cast<uint16_t>(src[0])
        | (static_cast<uint16_t>(src[1]) << 8)
    );
}

void Dwm1000RangingDriver::makeHeader(
    uint8_t* frame,
    const uint8_t type,
    const uint8_t seq,
    const uint16_t src,
    const uint16_t dst
) {
    frame[0] =
        MAGIC0;
    frame[1] =
        MAGIC1;
    frame[2] =
        type;
    frame[3] =
        seq;
    writeU16(
        frame + 4,
        src
    );
    writeU16(
        frame + 6,
        dst
    );
}

bool Dwm1000RangingDriver::validHeader(
    const uint8_t* frame,
    const uint16_t len,
    const uint16_t ownShortAddress
) {
    if (
        len < HEADER_LEN
        || frame[0] != MAGIC0
        || frame[1] != MAGIC1
    ) {
        return false;
    }

    const uint16_t dst =
        readU16(frame + 6);

    return dst == ownShortAddress;
}

double Dwm1000RangingDriver::calculateDsTwrDistanceM(
    const uint64_t pollTx,
    const uint64_t pollRx,
    const uint64_t respTx,
    const uint64_t respRx,
    const uint64_t finalTx,
    const uint64_t finalRx
) {
    const double ra =
        static_cast<double>(
            diff40(respRx, pollTx)
        );
    const double rb =
        static_cast<double>(
            diff40(finalRx, respTx)
        );
    const double da =
        static_cast<double>(
            diff40(finalTx, respRx)
        );
    const double db =
        static_cast<double>(
            diff40(respTx, pollRx)
        );

    const double denominator =
        ra + rb + da + db;

    if (denominator <= 0.0) {
        return -1.0;
    }

    const double tofTicks =
        ((ra * rb) - (da * db)) / denominator;

    return tofTicks * DISTANCE_PER_UWB_TICK_M;
}
