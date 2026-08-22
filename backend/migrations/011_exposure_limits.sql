-- 작업자 누적 노출량 기준값 시드 (FR-701, P0-A 완료).
--
-- 출처 원문: 고용노동부고시 제2020-48호(2020-01-14)
-- 「화학물질 및 물리적 인자의 노출기준」 별표 1.
-- 표의 TWA/STEL ppm 열을 CAS 번호까지 대조했다.
--   CO2 [124-38-9] : TWA 5,000 ppm / STEL 30,000 ppm
--   CO  [630-08-0] : TWA    30 ppm / STEL    200 ppm
--   H2S [7783-06-4]: TWA    10 ppm / STEL     15 ppm
--
-- dose_limit_ppm_min 은 별도 법정값이 아니라 TWA x 480분으로 파생한다.
-- O2 는 축적성 ppm 노출량이 아니며 009_exposure.sql 의 시간 기반 결핍 지표로
-- 판정하므로 이 테이블에 시드하지 않는다.

INSERT INTO exposure_limits
    (metric, twa_limit_ppm, dose_limit_ppm_min, stel_limit_ppm, reference)
VALUES
    (
        'co2_ppm', 5000, 2400000, 30000,
        '고용노동부고시 제2020-48호(2020-01-14), 별표 1, 이산화탄소 [124-38-9]'
    ),
    (
        'co_ppm', 30, 14400, 200,
        '고용노동부고시 제2020-48호(2020-01-14), 별표 1, 일산화탄소 [630-08-0]'
    ),
    (
        'h2s_ppm', 10, 4800, 15,
        '고용노동부고시 제2020-48호(2020-01-14), 별표 1, 황화수소 [7783-06-4]'
    )
ON CONFLICT (metric) DO UPDATE SET
    twa_limit_ppm = EXCLUDED.twa_limit_ppm,
    dose_limit_ppm_min = EXCLUDED.dose_limit_ppm_min,
    stel_limit_ppm = EXCLUDED.stel_limit_ppm,
    reference = EXCLUDED.reference,
    updated_at = now();
