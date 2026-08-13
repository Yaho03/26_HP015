import { useEffect, useRef } from "react";
import type { AlertLevel } from "../types";
import { WSClient } from "../services/wsClient";
import type { WSMessage } from "../types/ws";
import { useDashboardStore } from "../store/dashboardStore";
import { useToastStore } from "../store/toastStore";

const ALERT_TITLES: Record<string, string> = {
  co2_ppm: "CO₂ 경보",
  co_ppm: "CO 경보",
  h2s_ppm: "H₂S 경보",
  temperature_c: "온도 경보",
  o2_low: "O₂ 저농도",
  o2_high: "O₂ 고농도",
  fall_detection: "낙상 감지",
  connection_lost: "연결 끊김",
  zone_intrusion: "위험 구역 진입",
};

// 모든 경보를 node_id로 스코프한다 (이슈 #112). 이전엔 co2_ppm 등 가스 metric이
// node_id 없이 metric명 그대로 키가 돼서, active_alerts 딕셔너리에서 다른 노드의
// 같은 metric 경보가 서로 덮어썼다 — 예: sensor-01의 L2 경보가 sensor-03의 L1으로
// 덮어써지고, sensor-03이 정상 복귀하면 sensor-01 경보까지 함께 사라짐. 백엔드
// alert_publisher._active_alert_ids도 이미 (node_id, metric) 튜플로 관리하므로
// 프론트도 동일한 스코프 규칙으로 맞춘다.
function deriveAlertKey(metric: string, nodeId: string): string {
  return `${nodeId}:${metric}`;
}

function handleMessage(msg: WSMessage): void {
  const store = useDashboardStore.getState();
  const toastStore = useToastStore.getState();
  if (msg.type === "alert") {
    const key = deriveAlertKey(msg.metric, msg.node_id);
    if (msg.to_level === "normal") {
      store.resolveAlert(key);
    } else {
      store.addAlert({
        alert_key: key,
        node_id: msg.node_id,
        level: msg.to_level as AlertLevel,
        status: "active",
        trigger_value: msg.value,
        threshold: msg.threshold,
        activated_at: msg.timestamp,
        resolved_at: null,
      });
      const title = ALERT_TITLES[msg.metric] ?? msg.metric;
      const body = `${msg.node_id} · ${msg.value.toFixed(1)} / 임계값 ${msg.threshold}`;
      if (msg.to_level === "level3_critical") {
        toastStore.openModal({ level: "level3_critical", title, body });
      } else {
        toastStore.push({ level: msg.to_level as AlertLevel, title, body });
      }
    }
    if (msg.metric.startsWith("o2_") || msg.metric === "co2_ppm" || msg.metric === "co_ppm" || msg.metric === "h2s_ppm" || msg.metric === "temperature_c") {
      store.setSensorNodeReading(msg.node_id, msg.metric as never, msg.value, msg.timestamp);
    }
    return;
  }
  if (msg.type === "location") {
    store.setWearablePosition(msg.node_id, msg.x, msg.y, msg.z, msg.timestamp);
  }
}

export function useWebSocket(url: string): void {
  const clientRef = useRef<WSClient | null>(null);
  const setConnectionStatus = useDashboardStore((s) => s.setConnectionStatus);

  useEffect(() => {
    const client = new WSClient(url);
    clientRef.current = client;
    const offMessage = client.onMessage(handleMessage);
    const offStatus = client.onStatusChange((connected) => {
      setConnectionStatus({ websocket_connected: connected });
    });
    client.connect();
    return () => {
      offMessage();
      offStatus();
      client.disconnect();
      clientRef.current = null;
    };
  }, [url, setConnectionStatus]);
}
