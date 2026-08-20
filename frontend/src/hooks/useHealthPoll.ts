import { useEffect } from "react";
import { fetchHealth } from "../services/api";
import { useDashboardStore } from "../store/dashboardStore";

// 사이드바의 BE/MQTT 표시는 /health 를 봐야 알 수 있다 (이슈 #123).
// WS 연결 상태와 달리 스스로 알려주는 채널이 없어서 주기적으로 물어본다.
const POLL_MS = 5000;

/**
 * /health 를 주기 폴링해 백엔드·MQTT 연결 상태를 갱신한다.
 *
 * 요청이 실패하면 둘 다 끊김으로 내린다. 백엔드가 죽었는데 MQTT 만 살아 있다고
 * 표시하는 건 불가능하고, 안전 화면에서 낙관적 표시는 위험하다.
 */
export function useHealthPoll() {
  const setConnectionStatus = useDashboardStore((s) => s.setConnectionStatus);

  useEffect(() => {
    let cancelled = false;

    const tick = async () => {
      try {
        const health = await fetchHealth();
        if (cancelled) return;
        setConnectionStatus({
          backend_connected: true,
          mqtt_connected: health.mqtt.connected,
        });
      } catch {
        if (cancelled) return;
        setConnectionStatus({ backend_connected: false, mqtt_connected: false });
      }
    };

    void tick();
    const id = setInterval(() => void tick(), POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [setConnectionStatus]);
}
