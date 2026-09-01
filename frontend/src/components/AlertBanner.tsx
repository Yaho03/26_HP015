import { useEffect, useRef, useState } from "react";
import type { AlertState } from "../types";
import type { Projection } from "../utils/projection";
import { levelLabel } from "../utils/alerts";
import { alertMetricLabel, metricFromAlertKey } from "../utils/alertLabels";
import { shortNodeLabel } from "../utils/nodes";
import { LEVEL_ICON } from "./icons";

interface AlertBannerProps {
  /** 지금 띄울 경보. 활성 경보 중 가장 높은 등급 하나. 없으면 null. */
  alert: AlertState | null;
  /** 경보 시점 배정 작업자 이름. 미배정이면 null. */
  workerName: string | null;
  /** 그 노드의 도달 예측. 경보가 아니라 부가 정보다. */
  projection: Projection | null;
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("ko-KR", { hour12: false });
}

/** 수신 값은 신뢰 경계 밖이다 (#243). toFixed 가 throw 하면 경보 자체가 사라진다. */
function num(value: number): string {
  return Number.isFinite(value) ? value.toLocaleString("ko-KR") : String(value);
}

const SOUND_KEY = "hp015-alert-sound";

function playAlertTone(level: AlertState["level"]): void {
  const AudioContextClass = window.AudioContext;
  const context = new AudioContextClass();
  const count = level === "level3_critical" ? 3 : level === "level2_warning" ? 2 : 1;
  for (let i = 0; i < count; i += 1) {
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    const start = context.currentTime + i * 0.22;
    oscillator.type = "sine";
    oscillator.frequency.value = level === "level3_critical" ? 880 : 660;
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(0.12, start + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.16);
    oscillator.connect(gain).connect(context.destination);
    oscillator.start(start);
    oscillator.stop(start + 0.17);
  }
  window.setTimeout(() => void context.close(), count * 220 + 250);
}

/**
 * ② 경보 배너.
 *
 * 경보를 **가장 안 중요한 칸이 아니라 가장 잘 보이는 자리**에 둔다. 기존
 * `.alert-modal` 은 우상단에 고정돼 ②③ 을 덮었는데, 그건 경보를 읽는 동안
 * 정작 그 경보의 근거인 센서 카드가 가려진다는 뜻이었다.
 *
 * 문구는 네 단으로 읽힌다: **얼마나 급한가 → 어디가 → 왜 → 앞으로 어떻게 되나.**
 * 원인 지표와 임계값이 없으면 경보를 받은 사람이 다음 행동을 정할 수 없다.
 *
 * 추세 줄은 경보가 아니다 (06_ALERT_RULES §8.2). "추세" 라는 말을 앞에 붙여
 * 측정된 사실과 계산된 추정을 갈라 둔다.
 */
export function AlertBanner({ alert, workerName, projection }: AlertBannerProps) {
  // 확인한 경보는 접어 둔다. 등급이 오르거나 다른 노드에서 터지면 alert_key 나
  // level 이 달라지므로 다시 펼쳐진다 — 확인이 다음 경보까지 삼키지 않는다.
  const [acked, setAcked] = useState<{ stamp: string; at: string } | null>(null);
  const [soundOn, setSoundOn] = useState(
    () => typeof window !== "undefined" && window.localStorage.getItem(SOUND_KEY) === "on",
  );
  const sounded = useRef<string | null>(null);
  const alertStamp = alert ? `${alert.alert_key}:${alert.level}` : null;
  useEffect(() => {
    if (!soundOn || !alert || !alertStamp || sounded.current === alertStamp) return;
    sounded.current = alertStamp;
    playAlertTone(alert.level);
  }, [alert, alertStamp, soundOn]);
  if (!alert) return null;

  const stamp = `${alert.alert_key}:${alert.level}`;
  if (acked?.stamp === stamp) {
    return (
      <div className={"alert-banner alert-banner--acked is-" + alert.level} role="status">
        <span>경보 확인 완료</span>
        <strong>{shortNodeLabel(alert.node_id)}</strong>
        <time>{acked.at}</time>
        <button type="button" onClick={() => setAcked(null)}>다시 보기</button>
      </div>
    );
  }

  const LevelIcon = LEVEL_ICON[alert.level];
  const metric = metricFromAlertKey(alert.alert_key);
  const announcedLevel = projection?.level ?? alert.level;

  return (
    <div className={"alert-banner is-" + alert.level} role="alert" aria-live="assertive">
      <div className="alert-banner__head">
        <LevelIcon size={14} />
        <strong className="alert-banner__level">{levelLabel(alert.level)}</strong>
        <span className="alert-banner__node">{shortNodeLabel(alert.node_id)}</span>
        {workerName && <span className="alert-banner__worker">{workerName}</span>}
        <span className="alert-banner__time">{formatTime(alert.activated_at)}</span>
        <button
          type="button"
          className="alert-banner__sound"
          aria-pressed={soundOn}
          aria-label={soundOn ? "경보음 끄기" : "경보음 켜기"}
          onClick={() => {
            const next = !soundOn;
            setSoundOn(next);
            localStorage.setItem(SOUND_KEY, next ? "on" : "off");
            if (next) playAlertTone(alert.level);
          }}
        >
          {soundOn ? "경보음 켜짐" : "경보음 꺼짐"}
        </button>
        <button
          type="button"
          className="alert-banner__ack"
          onClick={() => setAcked({ stamp, at: new Date().toLocaleTimeString("ko-KR", { hour12: false }) })}
          aria-label="경보 확인"
        >
          확인
        </button>
      </div>

      <p className="alert-banner__message">
        <strong>{levelLabel(announcedLevel)}</strong>
        <span>
          {projection ? `${Math.max(1, Math.round(projection.minutes))}분 뒤 ` : "현재 "}
          {workerName ? `${workerName} 작업자에게 배정된` : "작업자 미배정"}{" "}
          {shortNodeLabel(alert.node_id)} 센서가 {levelLabel(announcedLevel)} 단계로
          {projection ? " 변경될 예정입니다." : " 변경되었습니다."}
        </span>
      </p>

      {/* 원인 지표와 임계값. 이게 없으면 무엇을 해야 할지 정할 수 없다. */}
      <div className="alert-banner__cause">
        <span className="alert-banner__metric">{alertMetricLabel(metric)}</span>
        <span className="alert-banner__value">{num(alert.trigger_value)}</span>
        <span className="alert-banner__limit">/ 임계 {num(alert.threshold)}</span>
      </div>

      {projection && (
        <div className="alert-banner__proj">
          <span className="alert-banner__proj-src">
            {projection.source === "lstm" ? "AI 예측" : "추세"}
          </span>
          약 {Math.round(projection.minutes)}분 뒤 {levelLabel(projection.level)}
        </div>
      )}
    </div>
  );
}
