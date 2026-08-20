# 다른 컴퓨터로 옮기기 — 2026-08-19

## 코드는 옮기지 않는다

전부 GitHub 에 있다. 옮길 컴퓨터에서:

```bash
git clone https://github.com/Yaho03/test_015.git
# 또는 이미 있으면
git pull origin main
```

현재 main = `4417b2b`. 오늘 커밋 11개가 모두 들어 있다
(결함 수정 8건 + 검증 증거 + 판정 도구 + 인수인계 문서).

**이 폴더에 있는 것은 `.gitignore` 때문에 GitHub 에 안 올라가는 것들뿐이다.**

---

## 1. config/ — 설정 파일 3개

git 에 올라가지 않는 파일들이다. clone 한 저장소에 같은 경로로 복사한다.

```
config/docker/.env                                  -> docker/.env
config/backend/.env                                 -> backend/.env
config/firmware/include/config/network_config.local.h -> 같은 경로
```

### 주의

- **`network_config.local.h` 는 이 노트북 전용이다.**
  SSID `iPad (74)`, 브로커 `172.20.10.13` 으로 되어 있다.
  옮길 컴퓨터의 WiFi 와 IP 로 반드시 고쳐야 한다.
  (브로커 IP = 그 컴퓨터의 WiFi IP. `localhost` 는 안 된다 — 보드가 자기 자신을 찾는다.)

- **`docker/.env` 에 `DEMO_CONTROL_ENABLED=true` 가 들어 있다.**
  데모 제어 API 를 켜는 값이다. 인증(#116) 전이라 열어두면 누구나 안전 시스템에
  가짜 값을 주입하거나 실제 경보를 정상값으로 덮을 수 있다. 시연 때만 켤 것.

- 두 `.env` 에 비밀번호가 들어 있다. 공유 채널에 올리지 말 것.

---

## 2. db/ — 오늘 측정 데이터

```
sensor_data.csv.gz    441,726 행   (2.9MB, 압축 전 36MB)
alert_events.csv          122 행
node_status.csv             4 행
thresholds.csv             18 행
```

**필요할 때만 옮기면 된다.** 보고서용 집계는 이미
`test_results/hardware/2026-08-19/csv/` 로 저장소에 들어가 있다.
이 원본은 재분석이 필요할 때 쓴다.

### 왜 SQL 덤프가 아니라 CSV 인가

`sensor_data` 는 TimescaleDB 하이퍼테이블이라 `pg_dump -t sensor_data` 로는
**데이터가 딸려오지 않는다** (실제 행이 `_timescaledb_internal` 청크에 있다).
실제로 시도했을 때 43KB 짜리 스키마만 나왔다. CSV 로 뽑아야 한다.

### 복원

새 컴퓨터에서 인프라를 띄운 뒤:

```bash
cd docker && docker compose up -d
# 마이그레이션이 자동 적용되어 빈 테이블이 생긴 뒤에
gunzip -c db/sensor_data.csv.gz | docker exec -i hp015-timescaledb \
  psql -U hp015 -d hp015 -c "COPY sensor_data FROM STDIN WITH CSV HEADER"
```

`thresholds` 는 마이그레이션이 기본값을 넣으므로 보통 복원할 필요가 없다.

---

## 3. 옮기지 않아도 되는 것

| 폴더 | 이유 |
|---|---|
| `C:\hp015build` | 펌웨어 빌드용 임시 복사본. 새 컴퓨터에서 다시 만들면 된다 |
| `26_HP015` (원래 폴더) | git 저장소가 아니고 내용은 전부 GitHub 에 있다 |
| `26_HP015_hw_session_20260819_backup` | 병합 전 백업. 모두 커밋 완료됨 |

---

## 4. 새 컴퓨터에서 할 일 순서

1. `git clone https://github.com/Yaho03/test_015.git`
2. `config/` 파일 3개 복사
3. `network_config.local.h` 의 SSID / 비밀번호 / 브로커 IP 를 그 환경에 맞게 수정
4. `cd docker && docker compose up -d` → `curl localhost:8000/health` 확인
5. 펌웨어 빌드는 **ASCII 경로에서** 할 것
   (한글 경로에서는 `wearable-node` 링크 실패 — 인수인계 문서 §3)
6. 필요하면 `db/` 복원

인수인계 문서: `docs/HW_SESSION_HANDOFF_20260819.md` (§1~§13)

---

## 5. results/ — 오늘 검증 결과와 증거

**GitHub 저장소에도 `test_results/hardware/2026-08-19/` 로 들어가 있다.**
여기 넣은 것은 clone 없이 바로 열어보기 위한 사본이다.

```
results/result_summary.md      판정 본문 (589줄) — 이슈별 §11 양식 기록
results/csv/01_요약통계.csv     항목별 표본수·평균·표준편차·최소·최대·변동계수
results/csv/02_원시데이터.csv   전체 원시 측정값 (35,656행)
results/csv/03_시계열_피벗.csv  ★ 엑셀 차트용 — 1초 단위, 항목이 열로 펼쳐짐
results/csv/04_R0교정추이.csv   분 단위 MQ R0 후보 추이
results/csv/05_경보이력.csv     경보 발생·발행지연·해제
results/csv/06_노드상태.csv     연결 상태·RSSI·가동시간
results/serial_*.log           보드별 시리얼 로그
results/db_checks.txt          DB 판정 출력
```

CSV 는 **UTF-8 BOM** 으로 저장해 엑셀에서 바로 열어도 한글이 안 깨진다.

### 보고서 쓸 때 주의

**`h2s_rs_ohm` 의 전체 CV 81.65% 를 그대로 인용하면 안 된다.**
센서 불안정이 아니라 06:02 창가 이동에 따른 환경 변화다.

```
06:01 이전  Rs 약  4,400 옴  (실내)
06:03 이후  Rs 약 21,000 옴  (창가, 청정 공기)
```

실내 미량 H2S 가 사라져 저항이 오른 것으로 센서가 정상 반응한 증거다.
이동 후 구간만 계산하면 CV 2.74%. 이동 시점(06:02)으로 분리해 기재할 것.

`db/sensor_data.csv.gz` 는 이 CSV 들의 원본(441,726행 전체)이다.
집계가 아니라 재분석이 필요할 때 쓴다.

---

## 6. docs/ — 문서

```
docs/HW_SESSION_HANDOFF_20260819.md   ★ 인수인계 (§1~§13). 다음 세션은 이것만 읽으면 된다
docs/HW_SESSION_PLAN.md               원래 세션 계획서 (오류 정정은 인수인계 §11 참조)
```

인수인계 문서에서 먼저 볼 곳:

- **§12.2** 보드별 최종 상태 — 어느 보드가 무엇이 문제인지
- **§12.7** 진단 절차 5단계 — 오늘 두 시간 걸린 길을 몇 분으로 줄이는 순서
- **§3** 빌드 환경 함정 — 한글 경로에서 wearable-node 링크 실패
- **§13** 병합 경위와 커밋 내역
