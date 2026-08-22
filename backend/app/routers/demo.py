"""데모 시나리오 제어 API (09_DEMO_SCENARIOS 4절).

대시보드 설정 화면에서 시연 시나리오를 켜고 끄기 위한 엔드포인트다.
`experiments/inject` CLI 를 자식 프로세스로 띄운다 — 이미 검증된 주입 경로를
그대로 쓰고, 시나리오 생성기를 백엔드로 복제하지 않기 위해서다.

보안:
- **기본 비활성.** 시뮬레이션 값을 원격 주입하는 기능이라 인증(#116)이 붙기 전에는
  열어두면 안 된다. settings.demo_control_enabled 가 false 면 404 를 낸다.
- **셸을 거치지 않는다.** create_subprocess_exec 에 argv 배열을 넘기므로 셸 확장이
  없다. 그래도 node_id 는 패턴으로 검증해 임의 문자열이 MQTT 토픽에 실리지 않게 한다.
"""
from __future__ import annotations

import asyncio
import logging
import re
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.dependencies.auth import require_role, verify_csrf

logger = logging.getLogger(__name__)

# 데모 제어는 가짜 값을 안전 시스템에 주입할 수 있다 — 전 엔드포인트 admin
# 전용 + 상태 변경에는 CSRF (역할 매트릭스 상 가장 강한 제한).
router = APIRouter(
    prefix="/api/demo",
    tags=["demo"],
    dependencies=[Depends(require_role("admin"))],
)

SENSOR_NODES = ["sensor-01", "sensor-02", "sensor-03", "sensor-04"]
WEARABLE_NODES = ["wearable-01"]

# 04_DATA_CONTRACT 의 node_id 규칙. 토픽 경로에 그대로 실리는 값이라 좁게 잡는다.
NODE_ID_RE = re.compile(r"^(?:sensor|wearable)-\d{2}$")


class ScenarioInfo(BaseModel):
    name: str
    label: str
    description: str
    default_nodes: List[str]
    supports_duration: bool
    default_duration_s: Optional[int] = None


# 표시용 카탈로그. name 은 scenarios.SCENARIOS 의 키와 일치해야 한다
# (tests/test_demo_control.py 가 대조한다).
CATALOG: List[ScenarioInfo] = [
    ScenarioInfo(
        name="normal_steady",
        label="정상 상태 모니터링",
        description="센서 4개가 L1 임계값 아래에서 계속 값을 보낸다. Scenario 1.",
        default_nodes=SENSOR_NODES,
        supports_duration=True,
        default_duration_s=300,
    ),
    ScenarioInfo(
        name="gas_spread",
        label="가스 확산",
        description="누출원(sensor-03)에서 거리순으로 CO₂ 가 올라 히트맵이 번진다.",
        default_nodes=SENSOR_NODES,
        supports_duration=True,
        default_duration_s=160,
    ),
    ScenarioInfo(
        name="worker_walk",
        label="작업자 위치 추적",
        description="웨어러블이 실험 공간을 5Hz 로 순회한다. Scenario 3.",
        default_nodes=WEARABLE_NODES,
        supports_duration=True,
        default_duration_s=300,
    ),
    ScenarioInfo(
        name="worker_walk_uwb",
        label="작업자 위치 추적 (UWB 삼변측량)",
        description="좌표 대신 앵커 거리를 보내고 백엔드가 계산한다. 실제 측위 경로.",
        default_nodes=WEARABLE_NODES,
        supports_duration=True,
        default_duration_s=300,
    ),
    ScenarioInfo(
        name="co2_warning",
        label="CO₂ 경보",
        description="정상 → L1 → L2 → L3 → 정상. 경보 전 구간을 짧게 훑는다.",
        default_nodes=["sensor-01"],
        supports_duration=False,
    ),
    ScenarioInfo(
        name="h2s_warning",
        label="H₂S 경보",
        description="H₂S 가 L3(10ppm)까지 올랐다 복귀한다.",
        default_nodes=["sensor-02"],
        supports_duration=False,
    ),
    ScenarioInfo(
        name="o2_low",
        label="O₂ 저농도",
        description="웨어러블 O₂ 가 16% 아래로 떨어진다.",
        default_nodes=WEARABLE_NODES,
        supports_duration=False,
    ),
    ScenarioInfo(
        name="fall_detection",
        label="낙상 감지",
        description="웨어러블 IMU 가 낙상을 보고한다.",
        default_nodes=WEARABLE_NODES,
        supports_duration=False,
    ),
    ScenarioInfo(
        name="node_offline",
        label="노드 오프라인",
        description="LWT 로 노드가 offline 으로 전환된다.",
        default_nodes=["sensor-01"],
        supports_duration=False,
    ),
]

_CATALOG_BY_NAME = {s.name: s for s in CATALOG}


class RunRequest(BaseModel):
    scenario: str
    node_ids: Optional[List[str]] = None
    duration_s: Optional[int] = Field(default=None, ge=1, le=3600)


class RunState(BaseModel):
    running: bool
    scenario: Optional[str] = None
    node_ids: List[str] = []
    started_at: Optional[str] = None


_process: Optional[asyncio.subprocess.Process] = None
_state = RunState(running=False)


def _guard() -> None:
    if not settings.demo_control_enabled:
        raise HTTPException(status_code=404, detail="demo control is disabled")


def _inject_cwd() -> Path:
    if settings.demo_inject_cwd:
        return Path(settings.demo_inject_cwd)
    # backend/app/routers/demo.py → 저장소 루트
    return Path(__file__).resolve().parents[3]


def _is_running() -> bool:
    return _process is not None and _process.returncode is None


@router.get("/scenarios", response_model=List[ScenarioInfo])
async def list_scenarios() -> List[ScenarioInfo]:
    _guard()
    return CATALOG


@router.get("/status", response_model=RunState)
async def status() -> RunState:
    _guard()
    return _state if _is_running() else RunState(running=False)


async def _terminate() -> None:
    global _process, _state
    if _is_running() and _process is not None:
        _process.terminate()
        try:
            await asyncio.wait_for(_process.wait(), timeout=5)
        except asyncio.TimeoutError:
            _process.kill()
            await _process.wait()
    _process = None
    _state = RunState(running=False)


@router.post("/stop", response_model=RunState)
async def stop(_csrf: None = Depends(verify_csrf)) -> RunState:
    _guard()
    await _terminate()
    return RunState(running=False)


@router.post("/run", response_model=RunState)
async def run(req: RunRequest, _csrf: None = Depends(verify_csrf)) -> RunState:
    _guard()

    info = _CATALOG_BY_NAME.get(req.scenario)
    if info is None:
        raise HTTPException(status_code=404, detail=f"unknown scenario: {req.scenario}")

    nodes = req.node_ids or info.default_nodes
    if not nodes:
        raise HTTPException(status_code=400, detail="node_ids must not be empty")
    for node_id in nodes:
        if not NODE_ID_RE.match(node_id):
            raise HTTPException(status_code=400, detail=f"invalid node_id: {node_id!r}")

    if req.duration_s is not None and not info.supports_duration:
        raise HTTPException(
            status_code=400, detail=f"{req.scenario} does not support duration"
        )
    duration = req.duration_s or (info.default_duration_s if info.supports_duration else None)

    # 한 번에 하나만 돌린다. 여러 시나리오가 같은 노드에 겹쳐 쓰면 화면이 무엇을
    # 보여주는지 알 수 없게 된다.
    await _terminate()

    # 셸을 쓰지 않는다 — argv 배열이라 인자가 셸 문법으로 해석되지 않는다.
    # MQTT 자격증명은 argv 에 두지 않는다 (#247): ps/procfs 에 노출된다.
    # inject CLI 가 읽는 환경변수(MQTT_USERNAME/MQTT_PASSWORD)로 전달한다.
    argv = [
        sys.executable, "-m", "experiments.inject.cli",
        "--scenario", info.name,
        "--node-id", ",".join(nodes),
        "--host", settings.mqtt_host,
        "--port", str(settings.mqtt_port),
    ]
    if duration is not None:
        argv += ["--duration", str(duration)]

    global _process, _state
    try:
        _process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(_inject_cwd()),
            env={**os.environ, "MQTT_USERNAME": settings.mqtt_username,
                 "MQTT_PASSWORD": settings.mqtt_password},
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError as exc:
        logger.exception("failed to launch inject tool")
        raise HTTPException(status_code=500, detail=f"failed to launch: {exc}") from exc

    _state = RunState(
        running=True,
        scenario=info.name,
        node_ids=nodes,
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    logger.info("demo scenario started: %s on %s", info.name, nodes)
    return _state
