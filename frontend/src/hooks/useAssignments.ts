import { useCallback, useEffect, useState } from "react";
import { fetchAssignments, type AssignedWorker } from "../services/api";

// 이슈 #136 — 노드 ID 로는 대피 지시를 못 한다. 현재 배정을 받아 화면이 사람을
// 부를 수 있게 한다. 배정은 사람이 장비를 차고 벗을 때만 바뀌므로 실시간
// 스트림에 태울 이유가 없다. 주기 갱신으로 충분하다.
const REFRESH_MS = 30000;

export function useAssignments() {
  const [assignments, setAssignments] = useState<AssignedWorker[]>([]);
  const [loaded, setLoaded] = useState(false);

  const reload = useCallback(async () => {
    const rows = await fetchAssignments();
    setAssignments(rows);
    setLoaded(true);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const rows = await fetchAssignments();
        if (!cancelled) {
          setAssignments(rows);
          setLoaded(true);
        }
      } catch {
        // 백엔드가 아직 안 떴을 수 있다. 다음 주기에 다시 시도한다.
      }
    };
    void load();
    const id = setInterval(() => void load(), REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  /** 노드를 착용 중인 작업자. 없으면 null — 이 상태 자체가 정보다. */
  const workerFor = useCallback(
    (nodeId: string) => assignments.find((a) => a.node_id === nodeId) ?? null,
    [assignments],
  );

  return { assignments, loaded, reload, workerFor };
}
