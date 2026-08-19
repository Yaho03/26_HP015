import json
import os
from datetime import datetime, timezone

import paho.mqtt.client as mqtt


# ============================================================
# MQTT
# ============================================================

BROKER = os.environ.get("MQTT_HOST", "localhost")
PORT = int(os.environ.get("MQTT_PORT", "1883"))
USERNAME = os.environ.get("MQTT_USERNAME", "")
PASSWORD = os.environ.get("MQTT_PASSWORD", "")

NODE_IDS = {
    "sensor-01",
    "sensor-02",
    "sensor-03",
    "sensor-04",
}


# ============================================================
# 고정 센서 위치
#
# 나중에 실제 좌표만 수정하면 됨.
# ============================================================

NODE_LOCATIONS = {
    "sensor-01": {"x": 0.0, "y": 0.0, "z": 0.0},
    "sensor-02": {"x": 0.0, "y": 0.0, "z": 0.0},
    "sensor-03": {"x": 0.0, "y": 0.0, "z": 0.0},
    "sensor-04": {"x": 0.0, "y": 0.0, "z": 0.0},
}


# ============================================================
# 저장 경로
# ============================================================

SCRIPT_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

PROJECT_DIR = os.path.dirname(
    SCRIPT_DIR
)

RESULT_DIR = os.path.join(
    PROJECT_DIR,
    "test_results"
)

RAW_DIR = os.path.join(
    RESULT_DIR,
    "raw"
)

PROCESSED_DIR = os.path.join(
    RESULT_DIR,
    "processed"
)

os.makedirs(
    RAW_DIR,
    exist_ok=True
)

os.makedirs(
    PROCESSED_DIR,
    exist_ok=True
)


# ============================================================
# 위험 단계
# ============================================================

STATUS_NAMES = {
    0: "normal",
    1: "caution",
    2: "warning",
    3: "danger",
}


# ============================================================
# 기준값 판정
# ============================================================

def classify_co2(value):

    if value is None:
        return None

    if value < 1000:
        return 0

    if value < 2000:
        return 1

    if value < 5000:
        return 2

    return 3


def classify_co(value):

    if value is None:
        return None

    if value < 25:
        return 0

    if value < 50:
        return 1

    if value < 200:
        return 2

    return 3


def classify_h2s(value):

    if value is None:
        return None

    if value < 1:
        return 0

    if value < 5:
        return 1

    if value < 10:
        return 2

    return 3


def classify_temperature(value):

    if value is None:
        return None

    if value < 35:
        return 0

    if value < 38:
        return 1

    if value < 40:
        return 2

    return 3


# ============================================================
# 센서 결과 형식
# ============================================================

def make_measurement(
    value,
    unit,
    classifier
):

    level = classifier(value)

    if level is None:

        return {
            "value": None,
            "unit": unit,
            "level": None,
            "status": "unavailable",
        }

    return {
        "value": value,
        "unit": unit,
        "level": level,
        "status": STATUS_NAMES[level],
    }


# ============================================================
# JSONL 저장
# ============================================================

def append_jsonl(
    path,
    record
):

    with open(
        path,
        "a",
        encoding="utf-8"
    ) as file:

        json.dump(
            record,
            file,
            ensure_ascii=False
        )

        file.write("\n")


# ============================================================
# 노드별 최신 상태
#
# gas와 env가 다른 주기로 들어오기 때문에
# 마지막 값을 노드별로 따로 기억한다.
# ============================================================

latest = {
    node_id: {
        "co2_ppm": None,
        "co_ppm": None,
        "h2s_ppm": None,
        "temperature_c": None,
        "sampled_at": None,
    }
    for node_id in NODE_IDS
}


# ============================================================
# RAW 저장
# ============================================================

def save_raw(
    node_id,
    topic,
    payload
):

    record = {
        "received_at":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "topic":
            topic,

        "payload":
            payload,
    }

    path = os.path.join(
        RAW_DIR,
        f"{node_id}.jsonl"
    )

    append_jsonl(
        path,
        record
    )


# ============================================================
# GAS 처리
# ============================================================

def update_gas(
    node_id,
    payload
):

    data = payload.get(
        "data",
        {}
    )

    state = latest[node_id]

    # 현재 MH-Z19B에서 직접 나오는 값
    state["co2_ppm"] = data.get(
        "co2_ppm"
    )


    # ---------------------------------------------
    # 아래 둘은 MQ 교정 완료 후 firmware에서
    # co_ppm / h2s_ppm을 넣으면 자동 사용됨.
    #
    # 현재 MQ raw ADC만으로 ppm을 임의 계산하지 않음.
    # ---------------------------------------------

    if data.get("co_estimated_ppm") is not None:

        state["co_ppm"] = data[
            "co_estimated_ppm"
        ]

    if data.get("h2s_estimated_ppm") is not None:

        state["h2s_ppm"] = data[
            "h2s_estimated_ppm"
        ]


    state["sampled_at"] = payload.get(
        "sampled_at"
    )


# ============================================================
# ENV 처리
# ============================================================

def update_env(
    node_id,
    payload
):

    data = payload.get(
        "data",
        {}
    )

    state = latest[node_id]

    state["temperature_c"] = data.get(
        "temperature_c"
    )

    state["sampled_at"] = payload.get(
        "sampled_at"
    )


# ============================================================
# 최종 전처리 데이터 생성
# ============================================================

def build_processed(
    node_id
):

    state = latest[node_id]


    co2 = make_measurement(
        state["co2_ppm"],
        "ppm",
        classify_co2
    )

    co = make_measurement(
        state["co_ppm"],
        "ppm",
        classify_co
    )

    h2s = make_measurement(
        state["h2s_ppm"],
        "ppm",
        classify_h2s
    )

    temperature = make_measurement(
        state["temperature_c"],
        "C",
        classify_temperature
    )


    # ---------------------------------------------
    # 전체 위험도 = 현재 사용할 수 있는 값 중 최대 Level
    # ---------------------------------------------

    levels = [
        measurement["level"]
        for measurement in [
            co2,
            co,
            h2s,
            temperature,
        ]
        if measurement["level"] is not None
    ]


    if levels:

        overall_level = max(
            levels
        )

        overall_status = (
            STATUS_NAMES[
                overall_level
            ]
        )

    else:

        overall_level = None
        overall_status = "unavailable"


    return {
        "node_id":
            node_id,

        "timestamp":
            state["sampled_at"],

        "location":
            NODE_LOCATIONS[node_id],

        "co2":
            co2,

        "co":
            co,

        "h2s":
            h2s,

        "temperature":
            temperature,

        "overall_level":
            overall_level,

        "overall_status":
            overall_status,
    }


# ============================================================
# 전처리 결과 저장
# ============================================================

def save_processed(
    node_id,
    processed
):

    path = os.path.join(
        PROCESSED_DIR,
        f"{node_id}.jsonl"
    )

    append_jsonl(
        path,
        processed
    )


# ============================================================
# MQTT 연결
# ============================================================

def on_connect(
    client,
    userdata,
    flags,
    reason_code,
    properties=None
):

    if reason_code != 0:

        print(
            "[MQTT] Connection failed:",
            reason_code
        )

        return


    print(
        "[MQTT] Connected."
    )


    # + = sensor-01, sensor-02 등 어떤 node_id든 한 자리 매칭
    client.subscribe(
        "sensors/+/gas",
        qos=1
    )

    client.subscribe(
        "sensors/+/env",
        qos=1
    )


    print(
        "[SUBSCRIBE] sensors/+/gas"
    )

    print(
        "[SUBSCRIBE] sensors/+/env"
    )


# ============================================================
# MQTT 메시지 도착
# ============================================================

def on_message(
    client,
    userdata,
    msg
):

    try:

        payload = json.loads(
            msg.payload.decode(
                "utf-8"
            )
        )

    except Exception as error:

        print(
            "[ERROR] JSON:",
            error
        )

        return


    # 예:
    # sensors/sensor-03/gas

    parts = msg.topic.split("/")

    if len(parts) != 3:
        return


    node_id = parts[1]
    data_type = parts[2]


    if node_id not in NODE_IDS:
        return


    # ========================================================
    # 1. RAW 그대로 저장
    # ========================================================

    save_raw(
        node_id,
        msg.topic,
        payload
    )


    # ========================================================
    # 2. 도착 즉시 해당 노드만 갱신
    # ========================================================

    if data_type == "gas":

        update_gas(
            node_id,
            payload
        )

    elif data_type == "env":

        update_env(
            node_id,
            payload
        )

    else:

        return


    # ========================================================
    # 3. 즉시 전처리
    # ========================================================

    processed = build_processed(
        node_id
    )


    # ========================================================
    # 4. 전처리 JSONL 저장
    # ========================================================

    save_processed(
        node_id,
        processed
    )


    # ========================================================
    # 5. 화면 확인
    # ========================================================

    print(
        f"[{node_id}] "
        f"CO2={processed['co2']['value']} "
        f"L{processed['co2']['level']} | "
        f"CO={processed['co']['value']} "
        f"L{processed['co']['level']} | "
        f"H2S={processed['h2s']['value']} "
        f"L{processed['h2s']['level']} | "
        f"T={processed['temperature']['value']} "
        f"L{processed['temperature']['level']} | "
        f"OVERALL={processed['overall_level']} "
        f"{processed['overall_status']}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "========================================"
    )

    print(
        " 4-Node Realtime Preprocessor"
    )

    print(
        "========================================"
    )

    print(
        f"BROKER: {BROKER}:{PORT}"
    )

    print(
        f"RAW: {RAW_DIR}"
    )

    print(
        f"PROCESSED: {PROCESSED_DIR}"
    )


    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="fixed-sensor-preprocessor"
    )

    client.on_connect = on_connect
    client.on_message = on_message

    if USERNAME:
        client.username_pw_set(
            USERNAME,
            PASSWORD
        )

    client.connect(
        BROKER,
        PORT,
        keepalive=60
    )


    try:

        client.loop_forever()

    except KeyboardInterrupt:

        print()
        print(
            "[SYSTEM] Logger stopped."
        )


if __name__ == "__main__":
    main()
