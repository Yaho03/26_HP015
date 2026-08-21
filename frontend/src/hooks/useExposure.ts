import { useEffect, useMemo, useRef } from "react";
import { useDashboardStore } from "../store/dashboardStore";
import { mockExposure, useExposureMock } from "../mocks/exposure";
import { fetchExposureCurrent } from "../services/api";
import type { WorkerExposureMessage } from "../types/ws";

/**
 * 새로고침 직후 한 번 REST 로 현재 상태를 받아 store 를 채운다 (§6.2).
 *
 * WebSocket 은 다음 브로드캐스트까지 최대 5초 아무것도 보내지 않는다 (§6.1 스로틀).
 * 그동안 화면이 "노출량 데이터 없음"으로 보이면, 실제로 8시간 누적이 쌓여 있는
 * 작업자를 노출이 없는 것처럼 표시하게 된다.
 *
 * 실패는 조용히 넘긴다 — 로그만 남기고 WS 갱신을 기다린다. 초기 로드 한 번 실패가
 * 화면 전체를 막을 이유는 없다.
 */
export function useExposureBootstrap(): void {
  const setWorkerExposure = useDashboardStore((s) => s.setWorkerExposure);
  const done = useRef(false);

  useEffect(() => {
    if (done.current) return;
    done.current = true;
    fetchExposureCurrent()
      .then((rows) => rows.forEach(setWorkerExposure))
      .catch((err) => console.warn("노출량 초기 로드 실패 — WS 갱신을 기다립니다", err));
  }, [setWorkerExposure]);
}

export interface ExposureView {
  exposure: WorkerExposureMessage | null;
  /** 목 데이터인가. 화면은 실측과 목을 구분해서 보여야 한다 (10_UI_FLOW §11). */
  is_mock: boolean;
}

/**
 * 웨어러블 노드 하나의 누적 노출량.
 *
 * **실측이 있으면 실측이 이긴다.** 백엔드가 붙은 뒤로는 목이 실제 데이터를 가리면
 * 안 된다 — 시연 중에 목을 켜둔 채로 진짜 경보를 못 보는 일이 생긴다.
 *
 * 목은 실측이 없을 때만, 그리고 개발자가 명시적으로 켰을 때만 나온다. 백엔드 없이
 * UI 를 확인하는 경로가 있어야 시연 리허설과 디버깅이 쉽다. is_mock 을 함께
 * 돌려주어 화면이 "지금 보고 있는 게 가짜"라는 사실을 숨기지 못하게 한다.
 */
export function useExposure(node_id: string): ExposureView {
  const live = useDashboardStore((s) => s.worker_exposure[node_id]) ?? null;
  const mockEnabled = useExposureMock((s) => s.enabled);
  const mockState = useExposureMock((s) => s.state);
  const mockSeed = useExposureMock((s) => s.seed);

  // 목 메시지는 상태가 바뀔 때만 새로 만든다. 렌더마다 새로 만들면 매번 새 객체가
  // 되어 memo 를 건 하위 컴포넌트가 전부 다시 그려진다.
  //
  // 기준 시각을 여기서 Date.now() 로 찍지 않고 스토어에서 받는 이유는 렌더
  // 순수성이다 (mocks/exposure.ts 의 seed 주석 참고).
  const mock = useMemo(
    () => (mockEnabled ? mockExposure(mockState, mockSeed) : null),
    [mockEnabled, mockState, mockSeed],
  );

  if (live) return { exposure: live, is_mock: false };
  if (mock) return { exposure: { ...mock, node_id }, is_mock: true };
  return { exposure: null, is_mock: false };
}
