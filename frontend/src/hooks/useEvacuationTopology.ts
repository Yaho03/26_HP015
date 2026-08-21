import { useEffect, useState } from "react";
import { fetchTopology } from "../services/evacuationApi";
import type { NavTopology } from "../types/evacuation";

/**
 * 통행 구조를 한 번 받아 둔다 (§4.2 GET /api/evacuation/topology).
 *
 * 주기 폴링을 하지 않는 이유: 통행 구조는 기동 시 YAML 에서 적재되고 프로세스가
 * 사는 동안 바뀌지 않는다. 출구 토글만 런타임에 바뀌는데, 그건 바꾼 화면이
 * 스스로 다시 받으면 된다.
 *
 * null 은 두 가지를 뜻한다 — 아직 안 왔거나(초기), 기능이 꺼져 있거나(409).
 * 둘 다 목 토폴로지로 대체해 화면이 비지 않게 한다. 어느 쪽인지는 비활성 배너가
 * 따로 말해준다.
 */
export function useEvacuationTopology(): {
  topology: NavTopology | null;
  reload: () => void;
} {
  const [topology, setTopology] = useState<NavTopology | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      try {
        const loaded = await fetchTopology();
        if (!cancelled) setTopology(loaded);
      } catch {
        // 백엔드가 없는 개발 환경이 정상 경로다. 목으로 떨어진다.
        if (!cancelled) setTopology(null);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [nonce]);

  return { topology, reload: () => setNonce((n) => n + 1) };
}
