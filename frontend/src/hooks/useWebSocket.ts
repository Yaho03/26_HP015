import { useEffect, useRef } from "react";
import type { AlertLevel, AlertState, MetricKey, SensorNodeState } from "../types";
import { WSClient } from "../services/wsClient";
import type { WSMessage } from "../types/ws";
import { useDashboardStore } from "../store/dashboardStore";
import { useToastStore } from "../store/toastStore";
import { useAuthStore } from "../store/authStore";

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

// 모든 경보를 node_id로 스코프한다 (이슈 #112, 코드리뷰 반영). 이전엔 co2_ppm 등 가스
// metric이 node_id 없이 metric명 그대로 키가 돼서, active_alerts 딕셔너리에서
// 다른 노드의 같은 metric 경보가 서로 덮어썼다 — 예: sensor-01의 L2 경보를
// sensor-03의 L1이 덮어쓰고, sensor-03이 정상 복귀하면 sensor-01 경보까지
// 함께 사라짐. connection_lost만 예외적으로 node_id를 붙이던 것도 통일해서
// 제거 — 백엔드 alert_publisher._active_alert_ids도 이미 (node_id, metric)
// 튜플로 관리하므로 프론트도 동일한 스코프 규칙(`${node_id}:${metric}`)으로 맞춘다.
// snapshot(ws_manager.py)도 동일 규칙으로 키를 만들어야 여기서 일관되게 매칭된다.
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
      if (toastStore.modal?.alert_key === key) toastStore.closeModal();
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
        toastStore.openModal({ alert_key: key, level: "level3_critical", title, body });
      } else {
        toastStore.push({ level: msg.to_level as AlertLevel, title, body });
      }
    }
    return;
  }
  if (msg.type === "location") {
    store.setWearablePosition(msg.node_id, msg.x, msg.y, msg.z, msg.timestamp, {
      position_raw: msg.position_raw,
      source_coordinate_system: msg.source_coordinate_system,
      source_mode: msg.source_mode,
    });
    return;
  }
  if (msg.type === "sensor_reading") {
    // 웨어러블 O₂ 는 센서 노드 카드가 아니라 웨어러블 카드 소관이다 (10_UI_FLOW 3.3).
    if (msg.node_id.startsWith("wearable-") && msg.metric === "o2_pct") {
      store.setWearableO2Reading(msg.node_id, msg.value, msg.timestamp);
      return;
    }
    store.setSensorNodeReading(msg.node_id, msg.metric as MetricKey, msg.value, msg.timestamp);
    return;
  }
  if (msg.type === "node_status") {
    store.setSensorNodeStatus(msg.node_id, {
      battery_pct: msg.battery_pct,
      wifi_rssi_dbm: msg.wifi_rssi_dbm,
      last_seen_at: msg.timestamp,
    });
    return;
  }
  if (msg.type === "snapshot") {
    const rawNodes = msg.nodes as Record<string, Partial<SensorNodeState>>;
    // snapshot도 실시간 sensor_reading과 동일하게 wearable을 분리해야 한다
    // (코드리뷰 반영) — 안 그러면 새로고침 시 wearable이 SENSOR NODES 카드에
    // 섞이고 WEARABLE 카드는 계속 비어 보인다(실제로 재현/확인함).
    const nodes: Record<string, Partial<SensorNodeState>> = {};
    for (const [node_id, patch] of Object.entries(rawNodes)) {
      if (node_id.startsWith("wearable-")) {
        const o2 = patch.readings?.o2_pct;
        if (o2) {
          store.setWearableO2Reading(node_id, o2.value, o2.sampled_at);
        }
        continue;
      }
      nodes[node_id] = patch;
    }
    const rawAlerts = msg.alerts as Record<
      string,
      { node_id: string; level: AlertLevel; trigger_value: number; threshold: number; activated_at: string }
    >;
    const alerts: Record<string, AlertState> = {};
    for (const [alert_key, a] of Object.entries(rawAlerts)) {
      alerts[alert_key] = {
        alert_key,
        node_id: a.node_id,
        level: a.level,
        status: "active",
        trigger_value: a.trigger_value,
        threshold: a.threshold,
        activated_at: a.activated_at,
        resolved_at: null,
      };
    }
    store.hydrateSnapshot(nodes, alerts);
  }
}

export function useWebSocket(url: string): void {
  const clientRef = useRef<WSClient | null>(null);
  const setConnectionStatus = useDashboardStore((s) => s.setConnectionStatus);
  const expire = useAuthStore((s) => s.expire);

  useEffect(() => {
    const client = new WSClient(url);
    clientRef.current = client;
    const offMessage = client.onMessage(handleMessage);
    const offStatus = client.onStatusChange((connected) => {
      setConnectionStatus({ websocket_connected: connected });
    });
    // WS close 1008 — 세션 만료. 재연결은 wsClient 가 이미 멈췄다 (#134).
    const offAuthExpired = client.onAuthExpired(() => expire());
    client.connect();
    return () => {
      offMessage();
      offStatus();
      offAuthExpired();
      client.disconnect();
      clientRef.current = null;
    };
  }, [url, setConnectionStatus, expire]);
}
