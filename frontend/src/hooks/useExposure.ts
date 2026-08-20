import { useMemo } from "react";
import { useDashboardStore } from "../store/dashboardStore";
import { mockExposure, useExposureMock } from "../mocks/exposure";
import type { WorkerExposureMessage } from "../types/ws";

export interface ExposureView {
  exposure: WorkerExposureMessage | null;
  /** 목 데이터인가. 화면은 실측과 목을 구분해서 보여야 한다 (10_UI_FLOW §11). */
  is_mock: boolean;
}

/**
 * 웨어러블 노드 하나의 누적 노출량.
 *
 * 목 모드가 켜져 있으면 목이 이긴다. 백엔드 적산 서비스가 스텁인 동안 화면을
 * 확인할 방법이 이것뿐이고, A5 이후에도 시연 리허설에 쓴다. 대신 is_mock 을 함께
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

  if (mock) return { exposure: { ...mock, node_id }, is_mock: true };
  return { exposure: live, is_mock: false };
}
