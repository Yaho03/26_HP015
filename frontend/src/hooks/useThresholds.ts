import { useCallback, useEffect } from "react";
import { fetchThresholds } from "../services/api";
import { useDashboardStore } from "../store/dashboardStore";

// PRD FR-204 — 임계값 정본은 서버다 (이슈 #114).
// 프론트에 숫자를 박아두면 설정에서 바꿔도 화면이 따라가지 않는다.

/** 못 받았을 때 재시도 간격. 임계값 없이는 등급 판정을 못 한다. */
const RETRY_MS = 5000;

/**
 * 부팅 시 서버 임계값을 적재한다. 실패하면 받을 때까지 재시도한다.
 *
 * 반환값으로 수동 갱신 함수를 준다 — 설정 화면에서 임계값을 저장한 뒤
 * 호출하면 대시보드 색이 바로 따라간다.
 */
export function useThresholds() {
  const setThresholds = useDashboardStore((s) => s.setThresholds);
  const loaded = useDashboardStore((s) => s.thresholds.length > 0);

  const reload = useCallback(async () => {
    setThresholds(await fetchThresholds());
  }, [setThresholds]);

  useEffect(() => {
    if (loaded) return;
    let cancelled = false;

    const load = async () => {
      try {
        const rows = await fetchThresholds();
        if (!cancelled) setThresholds(rows);
      } catch {
        // 백엔드가 아직 안 떴을 수 있다. 조용히 재시도한다.
      }
    };

    void load();
    const id = setInterval(() => void load(), RETRY_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [loaded, setThresholds]);

  return { loaded, reload };
}
