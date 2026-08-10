import { useDashboardStore } from "../store/dashboardStore";
import { NodeCard } from "../components/NodeCard";

export function MonitoringScreen() {
  const nodes = useDashboardStore((s) => s.sensor_nodes);
  const alerts = useDashboardStore((s) => s.active_alerts);
  const wearable = useDashboardStore((s) => s.wearable);

  const nodeList = Object.values(nodes);
  const alertList = Object.values(alerts).filter((a) => a.status === "active");

  return (
    <div className="screen">
      <section className="panel">
        <h2 className="panel-title">Sensor Nodes ({nodeList.length})</h2>
        {nodeList.length === 0 ? (
          <p className="panel-empty">연결된 센서 노드가 없습니다.</p>
        ) : (
          <ul className="node-grid">
            {nodeList.map((n) => (
              <li key={n.node_id} className="node-grid-item">
                <NodeCard node={n} />
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="panel">
        <h2 className="panel-title">Wearable</h2>
        {!wearable ? (
          <p className="panel-empty">연결된 웨어러블이 없습니다.</p>
        ) : (
          <NodeCard
            node={{
              node_id: wearable.node_id,
              readings: wearable.o2_pct !== null
                ? { o2_pct: { metric: "o2_pct", value: wearable.o2_pct, sampled_at: "" } }
                : {},
              battery_pct: wearable.battery_pct,
              wifi_rssi_dbm: null,
              connection_status: wearable.connection_status,
              last_seen_at: null,
            }}
          />
        )}
      </section>

      <section className="panel">
        <h2 className="panel-title">Active Alerts ({alertList.length})</h2>
        {alertList.length === 0 ? (
          <p className="panel-empty">활성 경보 없음.</p>
        ) : (
          <ul className="alert-list">
            {alertList.map((a) => (
              <li key={a.alert_key} className={"alert-row alert-" + a.level}>
                <span className="alert-key">{a.alert_key}</span>
                <span className="alert-node">{a.node_id}</span>
                <span className="alert-level">{a.level}</span>
                <span className="alert-value">
                  {a.trigger_value.toFixed(1)} / {a.threshold}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
