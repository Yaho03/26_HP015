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

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
