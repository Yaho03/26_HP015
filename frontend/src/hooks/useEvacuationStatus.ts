import { useEffect, useState } from "react";
import { fetchHealth, type EvacuationHealth } from "../services/api";

/**
 * 탈출 경로 기능이 살아 있는지 (FR-806, 12_EVACUATION_ROUTE_SPEC §6.3).
 *
 * 통행 구조 검증에 실패하면 백엔드는 경로 기능만 끄고 정상 기동한다. 화면이 그
 * 사실을 모르면 관제사는 **"경로가 안 뜨는 것"과 "안전한 경로가 없는 것"을
 * 구분할 수 없다.** 전자는 설정 문제고 후자는 대피 상황이다.
 *
 * useHealthPoll(5초)과 따로 도는 이유: 그 훅은 결과를 dashboardStore 에 쓰는데,
 * 그 파일은 노출량 기능과 공유하는 배선 완료 파일이라 슬롯을 추가할 수 없다.
 * 대신 주기를 훨씬 길게 잡는다 — 통행 구조는 기동 시 한 번 적재되고 프로세스가
 * 사는 동안 바뀌지 않으므로 자주 물어볼 이유가 없다.
 */
const POLL_MS = 30_000;

export function useEvacuationStatus(): EvacuationHealth | null {
  const [status, setStatus] = useState<EvacuationHealth | null>(null);

  useEffect(() => {
    let cancelled = false;

    const tick = async () => {
      try {
        const health = await fetchHealth();
        if (cancelled) return;
        // 필드가 없는 백엔드면 null 을 유지한다. "꺼짐"으로 단정하지 않는다 —
        // 알 수 없는 것과 꺼진 것은 다르고, 없는 배너를 띄우면 오히려 오해를 만든다.
        setStatus(health.evacuation ?? null);
      } catch {
        if (cancelled) return;
        // 백엔드가 안 떠 있는 것은 경로 기능이 꺼진 것과 다르다. 사이드바의
        // BE 표시가 이미 그 사실을 알리므로 여기서 배너를 겹쳐 띄우지 않는다.
        setStatus(null);
      }
    };

    void tick();
    const id = setInterval(() => void tick(), POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return status;
}
