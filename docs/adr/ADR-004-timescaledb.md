# ADR-004: 시계열 DB TimescaleDB 확정

| 항목 | 내용 |
|------|------|
| 상태 | Accepted |
| 결정일 | 2026-07-13 |
| 결정자 | 팀 합의 |

## 배경

시계열 DB 후보로 InfluxDB, TimescaleDB, SQLite를 검토했다. 백엔드를 FastAPI(Python)로 확정함에 따라 SQL 기반 DB가 ORM(SQLAlchemy) 통합에 유리하다. TimescaleDB는 PostgreSQL 확장이므로 기존 SQL 생태계, 도구, 확장 기능을 그대로 활용할 수 있다.

## 결정

TimescaleDB를 채택한다.

## 대안

| 대안 | 결과 | 이유 |
|------|------|------|
| TimescaleDB | 채택 | PostgreSQL 기반, SQL 친숙, FastAPI+SQLAlchemy 통합 용이, hypertable 자동 파티셔닝 |
| InfluxDB | 기각 | 자체 쿼리 언어(Flux/InfluxQL), Python ORM 통합 제한적, 학습 곡선 |
| SQLite | 기각 | 동시 쓰기 성능 부족, 시계열 특화 기능 없음, 대용량 데이터 처리 한계 |

## 결과

**긍정:**
- SQL 생태계 활용 (기존 PostgreSQL 도구, 확장, 관리 도구)
- 안정적인 동시성 처리 (다중 센서 노드 동시 쓰기)
- FastAPI + SQLAlchemy 자연스러운 통합
- hypertable을 통한 시간 기반 자동 파티셔닝
- 풍부한 PostgreSQL 확장 (PostGIS, pg_stat_statements 등)

**부정:**
- InfluxDB 대비 시계열 특화 함수가 적음
- PostgreSQL 설정 및 관리 오버헤드 (단일 노드에서는 미미)
