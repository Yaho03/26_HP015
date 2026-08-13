import { useEffect, useRef } from "react";
import type { AlertLevel, AlertState, MetricKey, SensorNodeState } from "../types";
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

function deriveAlertKey(metric: string, nodeId: string): string {
  if (metric === "o2_low" || metric === "o2_high") return metric;
  if (metric === "connection_lost") return `connection_lost:${nodeId}`;
  if (metric === "fall_detection") return "fall_detection";
  return metric;
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
    return;
  }
  if (msg.type === "location") {
    store.setWearablePosition(msg.node_id, msg.x, msg.y, msg.z, msg.timestamp);
    return;
  }
  if (msg.type === "sensor_reading") {
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
    const nodes = msg.nodes as Record<string, Partial<SensorNodeState>>;
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
