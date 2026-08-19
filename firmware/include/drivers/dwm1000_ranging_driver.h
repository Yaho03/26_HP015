#pragma once

#include <Arduino.h>
#include <UWB_DW1000.h>

enum class Dwm1000Role : uint8_t {
    ANCHOR_NODE,
    TAG_NODE
};

struct Dwm1000Range {
    const char* anchorId = nullptr;
    uint16_t shortAddress = 0;
    float distanceM = 0.0F;
    float rxPowerDbm = 0.0F;
    unsigned long updatedMs = 0;
    bool valid = false;
};

class Dwm1000RangingDriver {
public:
    static constexpr size_t MAX_ANCHOR_RANGES = 4;

    Dwm1000RangingDriver(
        Dwm1000Role role,
        const char* eui,
        uint16_t shortAddress,
        int8_t sckPin,
        int8_t misoPin,
        int8_t mosiPin,
        int8_t csPin,
        int8_t rstPin,
        int8_t irqPin
    );

    bool begin();
    void loop();

    bool isReady() const;
    bool hasNewRange() const;
    void clearNewRangeFlag();

    size_t copyFreshRanges(
        Dwm1000Range* out,
        size_t maxCount,
        unsigned long maxAgeMs
    ) const;

    const String& deviceIdentifier() const;
    const String& eui() const;
    const char* roleName() const;

private:
    enum class TagState : uint8_t {
        IDLE,
        WAIT_POLL_TX,
        WAIT_RESP,
        WAIT_RESULT
    };

    enum class AnchorState : uint8_t {
        WAIT_POLL,
        WAIT_FINAL
    };

    static Dwm1000RangingDriver* active_;

    static void onTxDone();
    static void onRxDone();
    static void onIrq();

    void processIrq();
    void processTxDone();
    void processRxDone();
    void processTagRx(uint64_t rxTs, const uint8_t* frame, uint16_t len);
    void processAnchorRx(uint64_t rxTs, const uint8_t* frame, uint16_t len);
    void sendTagPoll();
    void sendAnchorResult(uint8_t seq, double distanceM, uint64_t finalRxTs);
    void storeRange(uint16_t anchorShortAddress, float distanceM, float rxPowerDbm);

    static const char* anchorIdForShortAddress(uint16_t shortAddress);
    static uint32_t uusToUwbTicks(uint32_t uus);
    static uint64_t diff40(uint64_t later, uint64_t earlier);
    static void writeTs40(uint8_t* dst, uint64_t value);
    static uint64_t readTs40(const uint8_t* src);
    static void writeU16(uint8_t* dst, uint16_t value);
    static uint16_t readU16(const uint8_t* src);
    static void writeI32(uint8_t* dst, int32_t value);
    static int32_t readI32(const uint8_t* src);
    static void writeI16(uint8_t* dst, int16_t value);
    static int16_t readI16(const uint8_t* src);
    static void makeHeader(
        uint8_t* frame,
        uint8_t type,
        uint8_t seq,
        uint16_t src,
        uint16_t dst
    );
    static bool validHeader(
        const uint8_t* frame,
        uint16_t len,
        uint16_t ownShortAddress
    );
    static double calculateDsTwrDistanceM(
        uint64_t pollTx,
        uint64_t pollRx,
        uint64_t respTx,
        uint64_t respRx,
        uint64_t finalTx,
        uint64_t finalRx
    );

    Dwm1000Role role_;
    String eui_;
    uint16_t shortAddress_;
    int8_t sckPin_;
    int8_t misoPin_;
    int8_t mosiPin_;
    int8_t csPin_;
    int8_t rstPin_;
    int8_t irqPin_;
    bool ready_ = false;
    bool hasNewRange_ = false;
    String deviceIdentifier_ = "";
    Dwm1000Range ranges_[MAX_ANCHOR_RANGES];
    UWB_DW1000 uwb_;

    volatile bool txComplete_ = false;
    volatile bool rxComplete_ = false;
    volatile bool irqPending_ = false;

    uint16_t rxLength_ = 0;
    uint8_t rxBuffer_[128] = {};

    TagState tagState_ = TagState::IDLE;
    AnchorState anchorState_ = AnchorState::WAIT_POLL;
    uint8_t seqCounter_ = 0;
    uint8_t currentSeq_ = 0;
    size_t currentAnchorIndex_ = 0;
    uint16_t currentTargetAnchor_ = 1;
    unsigned long stateStartedMs_ = 0;
    unsigned long lastRangeMs_ = 0;

    uint64_t pollTxTs_ = 0;
    uint64_t respRxTs_ = 0;
    uint64_t savedPollRxTs_ = 0;
    uint64_t savedRespTxTs_ = 0;
    uint16_t savedTagShortAddress_ = 0;
    uint8_t savedSeq_ = 0;

    static constexpr uint16_t ANCHOR_SHORT_ADDRESSES[MAX_ANCHOR_RANGES] = {
        1,
        2,
        3,
        4
    };
    static constexpr uint16_t ANTENNA_DELAY = 16436;
    static constexpr uint32_t RESP_DELAY_UUS = 5000;
    static constexpr uint32_t FINAL_DELAY_UUS = 5000;
    static constexpr uint32_t RESULT_DELAY_UUS = 3000;
    static constexpr uint32_t RANGE_PERIOD_MS = 250;
    static constexpr uint32_t RANGE_TIMEOUT_MS = 140;
    static constexpr uint32_t UUS_TO_UWB_TIME = 63898UL;
    static constexpr double DISTANCE_PER_UWB_TICK_M = 0.0046917639786159;
    static constexpr uint64_t UWB40_MASK = 0xFFFFFFFFFFULL;
    static constexpr uint8_t MAGIC0 = 0x55;
    static constexpr uint8_t MAGIC1 = 0xAA;
    static constexpr uint8_t MSG_POLL = 0x01;
    static constexpr uint8_t MSG_RESP = 0x02;
    static constexpr uint8_t MSG_FINAL = 0x03;
    static constexpr uint8_t MSG_RESULT = 0x04;
    static constexpr uint8_t HEADER_LEN = 8;
};
