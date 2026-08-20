import json
import os
import statistics

from collections import defaultdict, deque
from datetime import datetime

import paho.mqtt.client as mqtt


# ============================================================
# MQTT
# ============================================================

BROKER = os.environ.get("MQTT_HOST", "localhost")
PORT = int(os.environ.get("MQTT_PORT", "1883"))
USERNAME = os.environ.get("MQTT_USERNAME", "")
PASSWORD = os.environ.get("MQTT_PASSWORD", "")
QOS = 1

TOPICS = [
    ("sensors/+/+", QOS),
    ("wearable/+/+", QOS),
    ("thermal/+/+", QOS),
]


# ============================================================
# Files
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

os.makedirs(
    RESULT_DIR,
    exist_ok=True
)


RAW_FILE = os.path.join(
    RESULT_DIR,
    "raw_mqtt.jsonl"
)

CLEAN_FILE = os.path.join(
    RESULT_DIR,
    "cleaned_data.jsonl"
)


# ============================================================
# Filtering
# ============================================================

FILTER_WINDOW = 5

buffers = defaultdict(
    lambda: defaultdict(
        lambda: deque(
            maxlen=FILTER_WINDOW
        )
    )
)


def append_jsonl(path, record):

    with open(
        path,
        "a",
        encoding="utf-8"
    ) as f:

        json.dump(
            record,
            f,
            ensure_ascii=False
        )

        f.write("\n")


def validate_range(
    value,
    minimum,
    maximum
):

    if value is None:
        return None

    try:
        value = float(value)

    except (ValueError, TypeError):
        return None

    if value < minimum:
        return None

    if value > maximum:
        return None

    return value


def median_filter(
    device_id,
    key,
    value
):

    if value is None:
        return None

    try:
        value = float(value)

    except (ValueError, TypeError):
        return None

    buffer = buffers[device_id][key]

    buffer.append(value)

    return statistics.median(buffer)


# ============================================================
# Normal sensor node : GAS
# ============================================================

def preprocess_gas(
    node_id,
    envelope
):

    data = envelope.get(
        "data",
        {}
    )

    quality = envelope.get(
        "quality",
        {}
    )

    clean = {
        "device_type": "sensor",
        "type": "gas",
        "node_id": node_id,
        "sampled_at": envelope.get(
            "sampled_at"
        ),
        "sequence": envelope.get(
            "sequence"
        ),
    }


    # ----------------------------
    # CO2
    # ----------------------------

    co2_raw = validate_range(
        data.get("co2_ppm"),
        0,
        10000
    )

    clean["co2_ppm_raw"] = co2_raw

    clean["co2_ppm_filtered"] = (
        median_filter(
            node_id,
            "co2_ppm",
            co2_raw
        )
    )


    # ----------------------------
    # MQ-7 / CO
    # ----------------------------

    mq7_v = validate_range(
        data.get("co_voltage_v"),
        0,
        5
    )

    clean["mq7_voltage_raw"] = mq7_v

    clean["mq7_voltage_filtered"] = (
        median_filter(
            node_id,
            "mq7_voltage",
            mq7_v
        )
    )

    mq7_rs = data.get(
        "co_rs_ohm"
    )

    clean["mq7_rs_ohm_raw"] = mq7_rs

    clean["mq7_rs_ohm_filtered"] = (
        median_filter(
            node_id,
            "mq7_rs",
            mq7_rs
        )
    )


    # ----------------------------
    # MQ-136 / H2S
    # ----------------------------

    mq136_v = validate_range(
        data.get("h2s_voltage_v"),
        0,
        5
    )

    clean["mq136_voltage_raw"] = mq136_v

    clean["mq136_voltage_filtered"] = (
        median_filter(
            node_id,
            "mq136_voltage",
            mq136_v
        )
    )

    mq136_rs = data.get(
        "h2s_rs_ohm"
    )

    clean["mq136_rs_ohm_raw"] = mq136_rs

    clean["mq136_rs_ohm_filtered"] = (
        median_filter(
            node_id,
            "mq136_rs",
            mq136_rs
        )
    )


    # ----------------------------
    # MQ-2
    # ----------------------------

    mq2_v = validate_range(
        data.get("mq2_voltage_v"),
        0,
        5
    )

    clean["mq2_voltage_raw"] = mq2_v

    clean["mq2_voltage_filtered"] = (
        median_filter(
            node_id,
            "mq2_voltage",
            mq2_v
        )
    )

    mq2_rs = data.get(
        "mq2_rs_ohm"
    )

    clean["mq2_rs_ohm_raw"] = mq2_rs

    clean["mq2_rs_ohm_filtered"] = (
        median_filter(
            node_id,
            "mq2_rs",
            mq2_rs
        )
    )


    # ----------------------------
    # BME680 gas
    # ----------------------------

    gas_r = data.get(
        "gas_resistance_ohm"
    )

    clean[
        "gas_resistance_ohm_raw"
    ] = gas_r

    clean[
        "gas_resistance_ohm_filtered"
    ] = median_filter(
        node_id,
        "bme_gas",
        gas_r
    )

    clean["iaq_index"] = (
        data.get("iaq_index")
    )

    clean["iaq_accuracy"] = (
        data.get("iaq_accuracy")
    )


    # ----------------------------
    # Quality
    # ----------------------------

    sensors = quality.get(
        "sensors",
        {}
    )

    clean["mq7_quality"] = (
        sensors.get("mq-7")
    )

    clean["mq136_quality"] = (
        sensors.get("mq-136")
    )

    clean["mq2_quality"] = (
        sensors.get("mq-2")
    )

    clean["mhz19b_quality"] = (
        sensors.get("mh-z19b")
    )

    clean["message_status"] = (
        quality.get("message_status")
    )

    return clean


# ============================================================
# Normal sensor node : ENV
# ============================================================

def preprocess_env(
    node_id,
    envelope
):

    data = envelope.get(
        "data",
        {}
    )

    clean = {
        "device_type": "sensor",
        "type": "env",
        "node_id": node_id,
        "sampled_at": envelope.get(
            "sampled_at"
        ),
        "sequence": envelope.get(
            "sequence"
        ),
    }


    temp = validate_range(
        data.get("temperature_c"),
        -40,
        85
    )

    humidity = validate_range(
        data.get("humidity_pct"),
        0,
        100
    )

    pressure = validate_range(
        data.get("pressure_hpa"),
        300,
        1100
    )


    clean["temperature_c_raw"] = temp

    clean[
        "temperature_c_filtered"
    ] = median_filter(
        node_id,
        "temperature",
        temp
    )


    clean["humidity_pct_raw"] = humidity

    clean[
        "humidity_pct_filtered"
    ] = median_filter(
        node_id,
        "humidity",
        humidity
    )


    clean["pressure_hpa_raw"] = pressure

    clean[
        "pressure_hpa_filtered"
    ] = median_filter(
        node_id,
        "pressure",
        pressure
    )


    return clean


# ============================================================
# Normal sensor node : STATUS
# ============================================================

def preprocess_status(
    node_id,
    envelope
):

    data = envelope.get(
        "data",
        {}
    )

    return {
        "device_type": "sensor",
        "type": "status",
        "node_id": node_id,

        "sampled_at": envelope.get(
            "sampled_at"
        ),

        "sequence": envelope.get(
            "sequence"
        ),

        "wifi_rssi_dbm": data.get(
            "wifi_rssi_dbm"
        ),

        "uptime_s": data.get(
            "uptime_s"
        ),
    }


# ============================================================
# Wearable : IMU
# ============================================================

def preprocess_imu(
    node_id,
    envelope
):

    data = envelope.get(
        "data",
        envelope
    )

    device_key = (
        f"wearable:{node_id}"
    )

    clean = {
        "device_type": "wearable",
        "type": "imu",
        "node_id": node_id,

        "sampled_at": envelope.get(
            "sampled_at"
        ),
    }


    # accelerometer
    for axis in ["ax", "ay", "az"]:

        raw = validate_range(
            data.get(axis),
            -20,
            20
        )

        clean[f"{axis}_raw"] = raw

        clean[f"{axis}_filtered"] = (
            median_filter(
                device_key,
                axis,
                raw
            )
        )


    # acceleration magnitude
    magnitude = validate_range(
        data.get("magnitude"),
        0,
        30
    )

    clean["magnitude_raw"] = magnitude

    clean[
        "magnitude_filtered"
    ] = median_filter(
        device_key,
        "magnitude",
        magnitude
    )


    # gyroscope
    for axis in ["gx", "gy", "gz"]:

        raw = validate_range(
            data.get(axis),
            -2000,
            2000
        )

        clean[f"{axis}_raw"] = raw

        clean[f"{axis}_filtered"] = (
            median_filter(
                device_key,
                axis,
                raw
            )
        )


    return clean


# ============================================================
# Wearable : Vital / O2
# ============================================================

def preprocess_vital(
    node_id,
    envelope
):

    data = envelope.get(
        "data",
        envelope
    )

    device_key = (
        f"wearable:{node_id}"
    )

    o2_raw = validate_range(
        data.get("o2_pct"),
        0,
        25
    )

    o2_filtered = median_filter(
        device_key,
        "o2_pct",
        o2_raw
    )

    return {
        "device_type": "wearable",
        "type": "vital",
        "node_id": node_id,

        "sampled_at": envelope.get(
            "sampled_at"
        ),

        "o2_pct_raw": o2_raw,

        "o2_pct_filtered":
            o2_filtered,
    }


# ============================================================
# Thermal : MLX90640
# ============================================================

def preprocess_thermal(
    node_id,
    envelope
):

    data = envelope.get(
        "data",
        envelope
    )

    device_key = (
        f"thermal:{node_id}"
    )


    min_temp = validate_range(
        data.get("min_temp_c"),
        -40,
        300
    )

    max_temp = validate_range(
        data.get("max_temp_c"),
        -40,
        300
    )

    avg_temp = validate_range(
        data.get("avg_temp_c"),
        -40,
        300
    )


    min_filtered = median_filter(
        device_key,
        "min_temp",
        min_temp
    )

    max_filtered = median_filter(
        device_key,
        "max_temp",
        max_temp
    )

    avg_filtered = median_filter(
        device_key,
        "avg_temp",
        avg_temp
    )


    hotspot_x = data.get(
        "hotspot_x"
    )

    hotspot_y = data.get(
        "hotspot_y"
    )


    clean = {
        "device_type": "thermal",

        "type": "summary",

        "node_id": node_id,

        "sampled_at": envelope.get(
            "sampled_at"
        ),

        "min_temp_c_raw":
            min_temp,

        "min_temp_c_filtered":
            min_filtered,

        "max_temp_c_raw":
            max_temp,

        "max_temp_c_filtered":
            max_filtered,

        "avg_temp_c_raw":
            avg_temp,

        "avg_temp_c_filtered":
            avg_filtered,

        "hotspot_x":
            hotspot_x,

        "hotspot_y":
            hotspot_y,
    }


    # 간단한 값 관계 검사
    if (
        min_filtered is not None
        and avg_filtered is not None
        and max_filtered is not None
    ):

        clean[
            "thermal_valid"
        ] = (
            min_filtered
            <= avg_filtered
            <= max_filtered
        )

    else:

        clean[
            "thermal_valid"
        ] = False


    return clean


# ============================================================
# MQTT
# ============================================================

def on_connect(
    client,
    userdata,
    flags,
    reason_code,
    properties=None
):

    print()
    print(
        "======================================"
    )

    print(
        " Integrated MQTT preprocessing logger"
    )

    print(
        "======================================"
    )

    print(
        f"BROKER : {BROKER}:{PORT}"
    )

    print()

    if reason_code != 0:

        print(
            f"[ERROR] connection failed: "
            f"{reason_code}"
        )

        return


    print("[MQTT] Connected.")


    for topic, qos in TOPICS:

        client.subscribe(
            topic,
            qos=qos
        )

        print(
            f"[SUB] {topic}"
        )


    print()
    print(
        "[LOGGER] Waiting for:"
    )

    print(
        "  sensor nodes"
    )

    print(
        "  wearable node"
    )

    print(
        "  thermal node"
    )

    print()


def on_message(
    client,
    userdata,
    msg
):

    try:

        text = msg.payload.decode(
            "utf-8"
        )

        envelope = json.loads(
            text
        )

    except Exception as error:

        print(
            f"[ERROR] JSON: {error}"
        )

        return


    received_at = (
        datetime.now()
        .astimezone()
        .isoformat()
    )


    # ========================================================
    # RAW 저장
    # ========================================================

    append_jsonl(
        RAW_FILE,
        {
            "received_at":
                received_at,

            "mqtt_topic":
                msg.topic,

            "payload":
                envelope,
        }
    )


    parts = msg.topic.split("/")

    if len(parts) != 3:
        return


    category = parts[0]
    node_id = parts[1]
    data_type = parts[2]


    cleaned = None


    # ========================================================
    # Normal sensor
    # ========================================================

    if category == "sensors":

        if data_type == "gas":

            cleaned = preprocess_gas(
                node_id,
                envelope
            )

        elif data_type == "env":

            cleaned = preprocess_env(
                node_id,
                envelope
            )

        elif data_type == "status":

            cleaned = preprocess_status(
                node_id,
                envelope
            )


    # ========================================================
    # Wearable
    # ========================================================

    elif category == "wearable":

        if data_type == "imu":

            cleaned = preprocess_imu(
                node_id,
                envelope
            )

        elif data_type == "vital":

            cleaned = preprocess_vital(
                node_id,
                envelope
            )


    # ========================================================
    # Thermal
    # ========================================================

    elif category == "thermal":

        if data_type == "summary":

            cleaned = (
                preprocess_thermal(
                    node_id,
                    envelope
                )
            )


    if cleaned is None:
        return


    cleaned["received_at"] = (
        received_at
    )


    append_jsonl(
        CLEAN_FILE,
        cleaned
    )


    print(
        f"[SAVE] "
        f"{category:<9} "
        f"{node_id:<12} "
        f"{data_type:<8}"
    )


# ============================================================
# Main
# ============================================================

def main():

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=
            "integrated-preprocessor"
    )


    client.on_connect = (
        on_connect
    )

    client.on_message = (
        on_message
    )

    if USERNAME:
        client.username_pw_set(
            USERNAME,
            PASSWORD
        )

    print(
        f"[MQTT] Connecting to "
        f"{BROKER}:{PORT}"
    )


    try:

        client.connect(
            BROKER,
            PORT,
            keepalive=60
        )

        client.loop_forever()


    except KeyboardInterrupt:

        print()
        print(
            "[LOGGER] stopped."
        )


    except Exception as error:

        print(
            f"[ERROR] {error}"
        )


if __name__ == "__main__":
    main()
