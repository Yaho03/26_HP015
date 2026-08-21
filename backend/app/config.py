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

    # 누적 노출량 적산 (FR-701~708, 11_EXPOSURE_DOSE_SPEC.md §4).
    #
    # 마지막 값을 최대 이만큼만 유지해 적산하고 초과분은 data_gap_s 로 보낸다 (§4.2).
    # 공백을 0 으로 간주하면 노출량을 과소평가하고, 무한 유지하면 하루 끊겼을 때
    # dose 가 천문학적으로 뛴다. 둘 다 위험해서 나온 절충값이다.
    exposure_gap_max_s: float = 60.0
    # exposure_state 로 flush 하는 주기 (§4.5). 백엔드가 죽었을 때의 손실 상한이
    # 곧 이 값이다 — 8시간 누적을 메모리에만 두지 않기 위한 것이다.
    exposure_flush_interval_s: float = 10.0
    # 농도 출처 노드까지의 거리로 신뢰도를 낮추는 경계 (§4.4).
    # 최근접 노드 실측값을 작업자 위치에 대입하는 방식이라(ADR-008) 멀수록 추정이
    # 약해진다. 그 약함을 숨기지 않고 trust_level 로 드러낸다.
    exposure_max_trust_distance_m: float = 3.0
    exposure_medium_trust_distance_m: float = 1.5

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
