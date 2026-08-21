# 노출기준 시드 확인 기록 (P0-A)

`backend/migrations/011_exposure_limits.sql` 이 `exposure_limits` 에 넣는 값의 근거와
확인 상태를 남긴다.

이 파일이 따로 있는 이유는 두 가지다.

1. **마이그레이션 파일은 동결이다.** 러너가 SHA-256 체크섬을 검증하므로
   (`backend/app/migration_runner.py`), 이미 적용된 뒤에는 **주석 한 글자만 고쳐도**
   그 DB 에서 부팅이 `checksum mismatch` 로 실패한다. 확인 기록처럼 나중에 덧붙게
   될 내용은 마이그레이션 안에 둘 수 없다.
2. 시드 자체는 근거가 아니다. `reference` 컬럼은 한 줄이고, "누가 무엇을 어디까지
   확인했는지"는 거기 안 들어간다.

---

## 1. 현재 시드된 값

| metric | 물질 | CAS | TWA (ppm) | STEL (ppm) | dose_limit (ppm·min) |
|---|---|---|---|---|---|
| `co2_ppm` | 이산화탄소 | 124-38-9 | 5,000 | 30,000 | 2,400,000 |
| `co_ppm` | 일산화탄소 | 630-08-0 | 30 | 200 | 14,400 |
| `h2s_ppm` | 황화수소 | 7783-06-4 | 10 | 15 | 4,800 |

- 출처로 기록된 원문: **고용노동부고시 제2020-48호(2020-01-14),
  「화학물질 및 물리적 인자의 노출기준」 별표 1**
- `dose_limit_ppm_min` 은 고시가 제시하는 값이 아니라 **`twa_limit_ppm × 480분`
  파생값**이다 (11_EXPOSURE_DOSE_SPEC §2.1). 산술 일치는
  `backend/tests/test_exposure_limits_seed.py` 가 파싱해서 검사한다.
- **`o2_pct` 는 의도적으로 시드하지 않는다.** 산소 결핍은 ppm·min 축적이 아니라
  시간(초) 기반 지표다 (§2.2). 여기에 행을 만들면 `dose_fraction` 이 산출되면서
  화면이 "산소 노출량 x%"라는 존재하지 않는 개념을 그린다.

## 2. 확인 상태 — ⚠️ 사람 서명 미완

사양서 §3.2 가 요구한 P0-A 는 **사람이 고시 원문을 펼쳐 대조하는 절차**다. 위 값은
그 절차의 결과로 커밋됐지만(`88c1e72`), **누가 원문을 확인했는지에 대한 기록이
남아 있지 않다.** 아래 두 줄이 채워지기 전까지 이 시드는 "확인됨"이 아니다.

```
확인자:
확인일:
확인한 원문 형태:   (국가법령정보센터 PDF / 고용노동부 고시 원문 / 인쇄본 중 하나)
```

### 남은 확인 항목 2개

**(a) 숫자 6개** — 위 표의 TWA·STEL 열을 별표 1 에서 CAS 번호로 행을 찾아 대조.

세 물질 모두 한국 고시값이 국제 기준과 다르므로, 다른 표를 봤다면 값이 갈린다.
그래서 이 셋은 특히 대조 가치가 있다.

| 물질 | 이 시드 (TWA/STEL) | ACGIH TLV (참고 — **근거 아님**) |
|---|---|---|
| CO | 30 / 200 | 25 / — |
| H₂S | 10 / 15 | 1 / 5 |
| CO₂ | 5,000 / 30,000 | 5,000 / 30,000 |

ACGIH 열은 "혹시 국제 기준표를 보고 적은 건 아닌지" 자가 점검용으로만 적었다.
**시드 근거로 인용하지 말 것** — DB CHECK 가 `reference` 에 `"ACGIH"` 같은 짧은
문자열을 거부하는 것과 같은 취지다.

**(b) 고시 호수가 현행인가** — 제2020-48호 이후 개정 고시가 있으면 `reference` 가
폐지된 판을 가리키게 된다. 값이 그대로여도 출처 표기는 틀린 것이 된다.

## 3. 값이 틀렸을 때 — 011 을 고치지 마라

체크섬 때문에 **불가능**하다. 정정은 새 마이그레이션으로 한다.

```
backend/migrations/012_exposure_limits_correction.sql
```

011 이 `ON CONFLICT (metric) DO UPDATE` 로 **모든** 안전 컬럼을 덮어쓰도록 쓰여
있으므로, 같은 형태의 INSERT 를 새 번호로 추가하면 정정이 반영된다
(`DO NOTHING` 이었다면 조용히 무시됐을 것이다).

정정 시 같이 고쳐야 하는 곳:

1. `backend/tests/test_exposure_limits_seed.py` 의 `PINNED` 상수
2. `frontend/src/mocks/exposure.ts` 의 `LIMIT` — 목 화면이 운영과 다른 기준을
   설명하지 않도록 같은 값을 쓴다. `frontend/src/utils/exposure.test.ts` 가 고정한다
3. 이 파일의 §1 표와 §2 서명

## 4. 이 기록을 무엇이 강제하는가

- `test_verification_record_exists_and_names_every_seeded_metric` — 시드된 metric 과
  CAS 가 전부 이 문서에 적혀 있는지 본다. 새 물질을 시드하면서 기록을 빠뜨리면 깨진다.
- `test_seed_values_are_pinned_against_silent_edits` — 확인된 숫자가 조용히 바뀌는
  것을 막는다. **통과가 "고시와 일치"를 뜻하지 않는다**; "마지막으로 사람이 확인한
  값에서 바뀌지 않았다"는 뜻이다.
- `test_exposure_limit_rejects_non_substantive_reference` (통합) — 출처가 비었거나
  한 단어면 실제 DB 가 INSERT 를 거부하는지 확인한다.
