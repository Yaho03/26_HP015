import { useEffect, useRef } from "react";
import { useDashboardStore } from "../store/dashboardStore";
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
}

/**
 * 웨어러블 노드 하나의 누적 노출량.
 *
 * 프론트는 시연 데이터를 만들지 않는다. 실측과 데모 모두 백엔드가 발행한
 * worker_exposure 메시지만 표시한다.
 */
export function useExposure(node_id: string): ExposureView {
  const live = useDashboardStore((s) => s.worker_exposure[node_id]) ?? null;
  return { exposure: live };
}
