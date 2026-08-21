#!/usr/bin/env python3
"""하드웨어 브링업 검증 도구 (#107 / #103 / #104).

수요일 하드웨어 세션에서 판정만 하도록 만든 것이다. 완료 조건은
HARDWARE_VERIFICATION_ISSUES.md 를 그대로 옮겼다.

  #107  실물 노드가 sensors/{id}/gas 를 발행 → sensor_data 에 INSERT
  #103  sampled_at 이 UTC 벽시계와 ±2초 이내 (NTP 동기 후)
  #104  3회 재부팅 후 message_id 집합에 교집합 없음

#104 를 DB 로 검증할 수 없는 이유:
    sensor_data 는 (time, node_id, metric, value, message_id) 만 저장하고
    boot_id / sequence 는 어디에도 남지 않는다. 게다가 message_id 가 재사용되면
    백엔드가 중복으로 판단해 조용히 버리므로, 재사용 사고일수록 DB 에 흔적이
    적게 남는다. 그래서 브로커를 직접 떠서 원본 발행을 본다.

사용법:
    # 1) 노드가 붙어 있는 동안 계속 켜 둔다. 재부팅 3회를 이 창에서 관찰한다.
    python scripts/hw_verify.py tap --node sensor-01

    # 2) 재부팅 3회가 끝나면 판정한다.
    python scripts/hw_verify.py check --node sensor-01

환경변수는 backend/.env 와 같은 키를 쓴다 (MQTT_HOST/PORT/USERNAME/PASSWORD,
TIMESCALE_URL).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_TAP = Path(__file__).resolve().parent.parent / ".hw_verify_tap.jsonl"

# #103 완료 조건의 허용 오차.
CLOCK_SKEW_TOLERANCE_S = 2.0
# #104 완료 조건이 요구하는 부팅 횟수.
REQUIRED_BOOTS = 3


def _env(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key, default)


def _load_dotenv(path: Path) -> None:
    """backend/.env 를 환경변수로 올린다. 이미 있는 값은 덮지 않는다."""
    if not path.exists():
        return
    # 저장소의 .env 예시는 UTF-8이고 Windows 기본 로케일은 CP949일 수 있다.
    # 인코딩을 생략하면 한글 주석이 있는 설정 파일에서 도구가 시작도 못 한다 (#197).
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


# ── tap ──────────────────────────────────────────────────────────────────

def cmd_tap(args: argparse.Namespace) -> int:
    """브로커를 구독해 발행 원본을 jsonl 로 적는다. Ctrl-C 로 종료."""
    import paho.mqtt.client as mqtt

    out = Path(args.out)
    # 이어붙인다 — 재부팅 사이에 탭을 껐다 켜도 기록이 이어지게 한다.
    fh = out.open("a", encoding="utf-8")
    seen = 0

    def on_connect(client, userdata, flags, rc, properties=None):
        if rc != 0:
            print(f"[tap] 브로커 연결 거부 rc={rc} — 자격증명을 확인하세요", file=sys.stderr)
            return
        for pattern in (f"sensors/{args.node}/#", f"nodes/{args.node}/connection"):
            client.subscribe(pattern)
        print(f"[tap] 구독 시작: {args.node} → {out}")
        print("[tap] 노드를 3회 재부팅한 뒤 Ctrl-C 로 종료하고 check 를 실행하세요.")

    def on_message(client, userdata, msg):
        nonlocal seen
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            print(f"[tap] 파싱 불가 payload 무시: {msg.topic}", file=sys.stderr)
            return
        record = {
            "topic": msg.topic,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "message_id": payload.get("message_id"),
            "boot_id": payload.get("boot_id"),
            "sequence": payload.get("sequence"),
            "sampled_at": payload.get("sampled_at"),
            "published_at": payload.get("published_at"),
            "time_synced": (payload.get("quality") or {}).get("time_synced"),
            "status": payload.get("status"),
        }
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        fh.flush()  # 재부팅/전원 순단으로 죽어도 기록이 남아야 한다
        seen += 1
        boot = (record["boot_id"] or "-")[:8]
        print(f"\r[tap] {seen}건  최근 boot_id={boot} seq={record['sequence']}", end="")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    username = _env("MQTT_USERNAME")
    if username:
        client.username_pw_set(username, _env("MQTT_PASSWORD"))
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(_env("MQTT_HOST", "localhost"), int(_env("MQTT_PORT", "1883")), 60)
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print(f"\n[tap] 종료. {seen}건 기록 → {out}")
    finally:
        fh.close()
    return 0


# ── check ────────────────────────────────────────────────────────────────

def _read_tap(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _check_104(rows: list[dict]) -> tuple[bool, list[str]]:
    """3회 재부팅 후 message_id 집합에 교집합이 없어야 한다."""
    notes = []
    telemetry = [r for r in rows if r.get("message_id")]
    if not telemetry:
        return False, ["telemetry 발행이 한 건도 관측되지 않음 — tap 을 먼저 돌리세요"]

    by_boot: dict[str, list[str]] = defaultdict(list)
    for r in telemetry:
        by_boot[r.get("boot_id") or "(boot_id 없음)"].append(r["message_id"])

    notes.append(f"관측된 부팅 세션: {len(by_boot)}개 (요구: {REQUIRED_BOOTS}회)")
    for boot, ids in by_boot.items():
        notes.append(f"  boot_id={boot[:12]}… 메시지 {len(ids)}건")

    if len(by_boot) < REQUIRED_BOOTS:
        return False, notes + [
            f"부팅 세션이 {REQUIRED_BOOTS}개 미만 — 재부팅을 더 하고 다시 판정하세요"
        ]

    # 세션 간 교집합
    boots = list(by_boot.items())
    overlaps = []
    for i in range(len(boots)):
        for j in range(i + 1, len(boots)):
            shared = set(boots[i][1]) & set(boots[j][1])
            if shared:
                overlaps.append(
                    f"boot {boots[i][0][:8]}… ∩ {boots[j][0][:8]}… = {len(shared)}건 "
                    f"(예: {sorted(shared)[0]})"
                )
    if overlaps:
        return False, notes + ["message_id 재사용 발견:"] + [f"  {o}" for o in overlaps]

    # 세션 내 중복도 사고다 (sequence 가 안 도는 경우)
    dupes = [b for b, ids in by_boot.items() if len(ids) != len(set(ids))]
    if dupes:
        return False, notes + [f"같은 부팅 안에서 message_id 중복: {len(dupes)}개 세션"]

    notes.append("세션 간·세션 내 message_id 중복 없음")
    return True, notes


def _check_103(rows: list[dict]) -> tuple[bool, list[str]]:
    """sampled_at 이 관측 시각(UTC 벽시계) 대비 ±2초 이내여야 한다."""
    notes = []
    samples = [r for r in rows if r.get("sampled_at") and r.get("observed_at")]
    if not samples:
        return False, ["sampled_at 을 담은 메시지가 관측되지 않음"]

    unsynced = [r for r in samples if r.get("time_synced") is False]
    if unsynced:
        notes.append(f"quality.time_synced=false 인 메시지 {len(unsynced)}건 — NTP 미동기 구간")

    worst = 0.0
    over = 0
    for r in samples:
        try:
            sampled = datetime.fromisoformat(r["sampled_at"].replace("Z", "+00:00"))
            observed = datetime.fromisoformat(r["observed_at"])
        except ValueError:
            continue
        skew = abs((observed - sampled).total_seconds())
        worst = max(worst, skew)
        if skew > CLOCK_SKEW_TOLERANCE_S:
            over += 1

    notes.append(f"관측 {len(samples)}건 중 ±{CLOCK_SKEW_TOLERANCE_S}s 초과 {over}건, 최대 편차 {worst:.2f}s")
    # 브로커 왕복 지연이 포함된 값이라 실제 시계 오차는 이보다 작다.
    notes.append("(관측 시각은 브로커 왕복을 포함하므로 실제 노드 시계 오차는 이보다 작다)")
    return over == 0, notes


def _check_107(node: str, since_minutes: int) -> tuple[bool, list[str]]:
    """실물 노드 발행이 sensor_data 에 INSERT 되었는지 본다.

    백엔드와 같은 드라이버(asyncpg)를 쓴다 — 별도 의존성을 늘리지 않는다.
    """
    import asyncio

    try:
        import asyncpg  # type: ignore
    except ImportError:
        return False, ["asyncpg 미설치 — backend/.venv 의 파이썬으로 실행하세요"]

    dsn = _env("TIMESCALE_URL")
    if not dsn:
        return False, ["TIMESCALE_URL 미설정 — backend/.env 를 확인하세요"]

    since = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)

    async def query():
        conn = await asyncpg.connect(dsn)
        try:
            return await conn.fetchrow(
                """
                SELECT count(*) AS rows, count(DISTINCT message_id) AS msgs,
                       count(DISTINCT metric) AS metrics, max(time) AS latest
                FROM sensor_data WHERE node_id = $1 AND time >= $2
                """,
                node, since,
            )
        finally:
            await conn.close()

    try:
        row = asyncio.run(query())
    except Exception as exc:  # 연결 실패도 판정 결과로 보여준다
        return False, [f"DB 조회 실패: {exc}"]

    notes = [
        f"최근 {since_minutes}분: {row['rows']}행 / 메시지 {row['msgs']}건 / metric {row['metrics']}종",
        f"마지막 적재 시각: {row['latest']}",
    ]
    return row["rows"] > 0, notes


def cmd_check(args: argparse.Namespace) -> int:
    rows = _read_tap(Path(args.tap))
    results = []

    ok107, n107 = _check_107(args.node, args.since_minutes)
    results.append(("#107 노드 발행 → sensor_data INSERT", ok107, n107))

    ok103, n103 = _check_103(rows)
    results.append(("#103 sampled_at NTP 동기 (±2s)", ok103, n103))

    ok104, n104 = _check_104(rows)
    results.append((f"#104 재부팅 {REQUIRED_BOOTS}회 message_id 무중복", ok104, n104))

    print(f"\n하드웨어 검증 — node={args.node}\n" + "=" * 52)
    for title, ok, notes in results:
        print(f"\n[{'PASS' if ok else 'FAIL'}] {title}")
        for n in notes:
            print(f"       {n}")

    failed = [t for t, ok, _ in results if not ok]
    print("\n" + "=" * 52)
    if failed:
        print(f"미통과 {len(failed)}건: {', '.join(failed)}")
        return 1
    print("전 항목 통과")
    return 0


def main() -> int:
    _load_dotenv(Path(__file__).resolve().parent.parent / "backend" / ".env")

    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    tap = sub.add_parser("tap", help="브로커 구독해서 발행 원본을 기록 (재부팅 동안 켜 둘 것)")
    tap.add_argument("--node", default="sensor-01")
    tap.add_argument("--out", default=str(DEFAULT_TAP))
    tap.set_defaults(func=cmd_tap)

    check = sub.add_parser("check", help="#107/#103/#104 완료 조건 판정")
    check.add_argument("--node", default="sensor-01")
    check.add_argument("--tap", default=str(DEFAULT_TAP))
    check.add_argument("--since-minutes", type=int, default=30)
    check.set_defaults(func=cmd_check)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
