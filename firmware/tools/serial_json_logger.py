import serial
import json
import os
from datetime import datetime

# =========================
# 설정
# =========================
PORT = os.environ.get("SERIAL_PORT", "COM10")
BAUD_RATE = int(os.environ.get("SERIAL_BAUD", "115200"))

BASE_DIR = "test_results"


def save_json(data):
    node_id = data.get("node_id", "unknown-node")
    sensor = data.get("sensor", "unknown-sensor")

    # test_results/sensor-01/
    node_dir = os.path.join(BASE_DIR, node_id)
    os.makedirs(node_dir, exist_ok=True)

    # test_results/sensor-01/mq7.jsonl
    file_path = os.path.join(
        node_dir,
        f"{sensor}.jsonl"
    )

    # PC 시간도 추가
    data["logged_at"] = datetime.now().isoformat(
        timespec="milliseconds"
    )

    with open(
        file_path,
        "a",
        encoding="utf-8"
    ) as f:
        f.write(
            json.dumps(
                data,
                ensure_ascii=False
            )
            + "\n"
        )


def main():

    print("==============================")
    print(" Sensor JSON Logger")
    print("==============================")
    print(f"PORT : {PORT}")
    print(f"BAUD : {BAUD_RATE}")
    print()

    try:
        ser = serial.Serial(
            PORT,
            BAUD_RATE,
            timeout=1
        )

    except serial.SerialException as e:
        print("[ERROR] Serial port open failed.")
        print(e)
        return

    print("[LOGGER] Serial connected.")
    print("[LOGGER] Waiting for JSON...")
    print("[LOGGER] Ctrl+C to stop.\n")

    try:

        while True:

            raw_line = ser.readline()

            if not raw_line:
                continue

            try:
                line = raw_line.decode(
                    "utf-8",
                    errors="ignore"
                ).strip()

            except Exception:
                continue

            # 터미널에서도 그대로 보기
            print(line)

            # [JSON]으로 시작하는 데이터만 저장
            if not line.startswith("[JSON]"):
                continue

            json_text = line[len("[JSON]"):].strip()

            try:
                data = json.loads(json_text)

            except json.JSONDecodeError:
                print(
                    "[LOGGER ERROR] Invalid JSON:",
                    json_text
                )
                continue

            save_json(data)

            print(
                f"[SAVED] "
                f"{data.get('node_id')} / "
                f"{data.get('sensor')}"
            )

    except KeyboardInterrupt:

        print("\n[LOGGER] Logging stopped.")

    finally:

        ser.close()
        print("[LOGGER] Serial closed.")


if __name__ == "__main__":
    main()
