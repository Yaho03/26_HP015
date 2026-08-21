from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """백엔드 설정. backend/.env 에서 값을 읽는다.

    실제 MQTT 수신(#44)·DB 연결(#50)에서 이 설정을 사용한다.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # MQTT (Mosquitto) — docker/ 인프라와 동일한 값
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: str = ""

    # TimescaleDB
    # 빈 기본값 허용(현재는 DB 연결 없음). 필수값 검증은 실제 연결이 들어가는 #50에서 추가한다.
    timescale_url: str = ""

    # CORS 허용 오리진 (콤마 구분, 이슈 #105). 와일드카드는 금지 — 배포 시 실제
    # 프론트엔드 오리진으로 교체한다.
    cors_origins: str = "http://localhost:5173"

    # Wearable/UWB location filtering (#110)
    location_filter_alpha: float = 0.3
    location_filter_max_speed_mps: float = 2.0
    location_filter_reject_limit: int = 5

    # 위치가 측정된 좌표계 (05_DIGITAL_TWIN_SPEC 3.1).
    # 축소 실험 장비는 demo-local, 실제 선박 좌표를 직접 받으면 ship-visual 로 둔다.
    # ship-visual 이면 프론트가 비율 매핑을 건너뛰므로 좌표가 두 번 확대되지 않는다.
    location_source_coordinate_system: str = "demo-local"

    # UWB 앵커 배치 (이슈 #121, ADR-006). "id:x,y;id:x,y" 형식.
    # 앵커 좌표는 설치 정보라 텔레메트리에 싣지 않고 서버가 안다.
    # 기본값은 축소 데모 공간(2.5 x 2.0m) 네 모서리.
    uwb_anchors: str = "A1:0,0;A2:2.5,0;A3:2.5,2.0;A4:0,2.0"

    # 비상 탈출 경로 (FR-801, 12_EVACUATION_ROUTE_SPEC §2.5).
    # 통행 구조(nav graph) 파일 경로. 비우면 저장소 루트의
    # config/space_topology.yaml 을 쓴다. 컨테이너 배포처럼 저장소 구조가 다른
    # 환경에서 경로만 바꿔 끼울 수 있어야 해서 설정으로 뺐다.
    evacuation_topology_path: str = ""

    # HazardZone 의 중심이 되는 고정 센서 노드의 ship-visual 좌표 (FR-803).
    # "id:x,y;id:x,y" 형식 — uwb_anchors 와 같은 규약이다.
    # 프론트엔드 utils/coordinates.ts 의 SENSOR_SHIP_POSITIONS 와 같은 값이어야
    # 화면의 히트맵과 경로가 같은 자리를 가리킨다.
    evacuation_sensor_positions: str = (
        "sensor-01:15,-3.25;sensor-02:45,-3.25;sensor-03:15,3.25;sensor-04:45,3.25"
    )

    # 경보가 뜬 노드 주변을 위험 구역으로 보는 반경.
    #
    # ⚠ **이 값은 가스 확산 범위의 추정치가 아니다.** "경보가 뜬 센서 근처를
    # 지나는 경로에 가중치를 준다"는 근접성 휴리스틱의 설정값일 뿐이다. 보고서나
    # 화면에서 확산 범위·안전 거리로 제시하면 안 된다.
    #
    # 표준 근거를 찾을 수 없어서가 아니라 그런 값이 없다 (08_SAFETY §3.5.3 조사).
    # 밀폐공간 규정의 판정 단위는 공간이지 원이 아니고 (OSHA 1910.146, 적정공기
    # 기준), 안전보건공단 지침은 오히려 수직·수평 3개소 이상 측정을 요구하며 그
    # 이유로 "같은 장소에서도 위치에 따라 농도 차가 현저하다"를 든다 — 한 점에서
    # 반경을 외삽하는 것이 바로 지침이 경계하는 가정이다. 실제 범위를 내려면
    # 누출원·환기량·격실 형상을 입력으로 하는 CFD 가 필요하고 셋 다 없다.
    #
    # 05_DIGITAL_TWIN_SPEC §5.1 의 0.5m 는 축소 데모 공간 기준이고, 60m
    # 화물창(ship-visual)에 그대로 쓰면 점이 된다. 센서는 y=±3.25 에 있고 통행로는
    # y=0 이라 0.5m 로는 **어떤 경보가 떠도 경로에 영향을 주지 못한다** — FR-803 이
    # 죽은 코드가 된다. 기본값 4.0 은 센서선에서 통행로까지 닿게 한 값이다.
    evacuation_hazard_radius_m: float = 4.0

    # 그래프에서 이보다 멀면 억지로 붙이지 않고 경로를 포기한다 (§3.3).
    evacuation_max_snap_distance_m: float = 5.0
    # 밀폐공간·보호구 착용을 감안한 보수적 보행 속도 (§4.1).
    evacuation_walk_speed_mps: float = 0.8
    # 새 경로가 현재 경로 비용의 이 비율 미만일 때만 교체한다 (§3.4).
    # 없으면 비용이 비슷한 두 경로 사이에서 화면이 좌우로 요동친다.
    evacuation_route_switch_ratio: float = 0.85
    # 위치가 이만큼 움직여야 재계산한다 (§3.4).
    evacuation_recompute_min_move_m: float = 0.5
    # 위치가 이보다 오래됐으면 경로를 산출하지 않는다 (§6.1).
    evacuation_position_max_age_s: float = 10.0

    # 데모 시나리오 제어 API (09_DEMO_SCENARIOS 4절).
    # 시뮬레이션 데이터를 원격으로 주입하는 기능이라 기본은 꺼둔다. 인증이 붙기 전
    # (#116) 이 열려 있으면 누구나 안전 시스템에 가짜 값을 밀어넣을 수 있고,
    # 실제 위험 상황에 정상값을 주입해 경보를 덮는 것도 가능하다.
    # 시연·개발 환경에서만 DEMO_CONTROL_ENABLED=true 로 켠다.
    demo_control_enabled: bool = False
    # 주입 도구 위치 (저장소 루트 기준). 컨테이너 배포본에는 없을 수 있다.
    demo_inject_cwd: str = ""

    # 인증 세션 (AUTH-2, ADR-007). 유휴 8h / 절대 12h (FR-604).
    session_idle_ttl_hours: float = 8.0
    session_absolute_ttl_hours: float = 12.0
    # HTTPS 운영에서만 true (Secure 쿠키 속성). 개발(http)에서는 false.
    cookie_secure: bool = False

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
