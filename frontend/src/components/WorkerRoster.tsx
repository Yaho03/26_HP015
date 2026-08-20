import { useCallback, useEffect, useState } from "react";
import {
  assignWorker,
  createWorker,
  deleteWorker,
  fetchAssignments,
  fetchWorkers,
  releaseNode,
  type AssignedWorker,
  type Worker,
} from "../services/api";

// 배정 대상 웨어러블. 데모 구성은 태그 1개다 (PRODUCT.md — 앵커 4 + 태그 1).
// 노드가 늘면 여기에 추가한다.
const WEARABLE_SLOTS = ["wearable-01"];

type Notice = { tone: "success" | "error"; text: string } | null;

const EMPTY_FORM = { employee_no: "", name: "", phone: "", emergency_contact: "" };

export function WorkerRoster() {
  const [workers, setWorkers] = useState<Worker[]>([]);
  const [assignments, setAssignments] = useState<AssignedWorker[]>([]);
  const [form, setForm] = useState(EMPTY_FORM);
  const [notice, setNotice] = useState<Notice>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    const [rows, active] = await Promise.all([fetchWorkers(), fetchAssignments()]);
    setWorkers(rows);
    setAssignments(active);
  }, []);

  useEffect(() => {
    void reload().catch(() => setNotice({ tone: "error", text: "명부를 불러오지 못했습니다." }));
  }, [reload]);

  /** 서버가 거절하면 그 이유를 그대로 보여준다 — 사번 중복·중복 배정 모두 사람이 고쳐야 한다. */
  const run = async (action: () => Promise<void>, ok: string) => {
    setBusy(true);
    try {
      await action();
      await reload();
      setNotice({ tone: "success", text: ok });
    } catch (error) {
      setNotice({ tone: "error", text: (error as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const assignedNodeOf = (workerId: number) =>
    assignments.find((a) => a.worker_id === workerId)?.node_id ?? null;

  const freeSlots = WEARABLE_SLOTS.filter(
    (slot) => !assignments.some((a) => a.node_id === slot),
  );

  return (
    <section className="settings-section" aria-labelledby="workers-title">
      <div className="settings-section-heading">
        <div>
          <p className="settings-section-kicker">OPERATE / WORKER REGISTRY</p>
          <h3 id="workers-title">작업자 명부 · 웨어러블 배정</h3>
        </div>
        <span className="settings-source">DB SOURCE · {workers.length} PERSONS</span>
      </div>

      <div className="settings-notice">
        <strong>경보가 사람 이름을 부르게 합니다</strong>
        <span>
          배정된 웨어러블에서 경보가 나면 <code>wearable-01</code> 대신 작업자 이름과
          비상연락처가 표시됩니다. 배정 이력은 시각과 함께 남아, 과거 경보를 조회하면
          그 시점의 착용자가 나옵니다.
        </span>
      </div>

      {notice && (
        <div
          className={
            "settings-notice " +
            (notice.tone === "error" ? "settings-notice--warning" : "settings-notice--ok")
          }
          role="status"
        >
          <span>{notice.text}</span>
        </div>
      )}

      <form
        className="worker-form"
        onSubmit={(event) => {
          event.preventDefault();
          void run(async () => {
            await createWorker({
              employee_no: form.employee_no.trim(),
              name: form.name.trim(),
              phone: form.phone.trim() || null,
              emergency_contact: form.emergency_contact.trim() || null,
            });
            setForm(EMPTY_FORM);
          }, "작업자를 등록했습니다.");
        }}
      >
        <label className="settings-field">
          <span>사번</span>
          <input
            required
            value={form.employee_no}
            onChange={(e) => setForm({ ...form, employee_no: e.target.value })}
            placeholder="2026-118"
          />
        </label>
        <label className="settings-field">
          <span>이름</span>
          <input
            required
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="김안전"
          />
        </label>
        <label className="settings-field">
          <span>연락처</span>
          <input
            value={form.phone}
            onChange={(e) => setForm({ ...form, phone: e.target.value })}
            placeholder="010-0000-0000"
          />
        </label>
        <label className="settings-field">
          <span>비상연락처</span>
          <input
            value={form.emergency_contact}
            onChange={(e) => setForm({ ...form, emergency_contact: e.target.value })}
            placeholder="010-0000-0000"
          />
        </label>
        <button type="submit" className="worker-submit" disabled={busy}>
          등록
        </button>
      </form>

      {workers.length === 0 ? (
        <p className="pending">
          등록된 작업자가 없습니다. 명부가 비어 있으면 경보는 노드 ID 만 표시합니다.
        </p>
      ) : (
        <table className="worker-table">
          <thead>
            <tr>
              <th>이름</th>
              <th>사번</th>
              <th>비상연락처</th>
              <th>착용 중</th>
              <th aria-label="작업" />
            </tr>
          </thead>
          <tbody>
            {workers.map((worker) => {
              const node = assignedNodeOf(worker.id);
              return (
                <tr key={worker.id}>
                  <td className="worker-table__name">{worker.name}</td>
                  <td>{worker.employee_no}</td>
                  <td>{worker.emergency_contact ?? <span className="pending">—</span>}</td>
                  <td>
                    {node ? (
                      <span className="worker-badge">{node}</span>
                    ) : (
                      <span className="pending">미배정</span>
                    )}
                  </td>
                  <td className="worker-table__actions">
                    {node ? (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() =>
                          void run(() => releaseNode(node), `${node} 배정을 해제했습니다.`)
                        }
                      >
                        해제
                      </button>
                    ) : (
                      freeSlots.map((slot) => (
                        <button
                          key={slot}
                          type="button"
                          disabled={busy}
                          onClick={() =>
                            void run(
                              () => assignWorker(worker.id, slot),
                              `${worker.name} → ${slot} 배정했습니다.`,
                            )
                          }
                        >
                          {slot} 배정
                        </button>
                      ))
                    )}
                    <button
                      type="button"
                      className="worker-delete"
                      disabled={busy}
                      onClick={() =>
                        void run(
                          () => deleteWorker(worker.id),
                          `${worker.name} 을(를) 명부에서 지웠습니다.`,
                        )
                      }
                    >
                      삭제
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}
