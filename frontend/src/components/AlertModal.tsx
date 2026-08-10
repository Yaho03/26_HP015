import { useEffect } from "react";
import { useToastStore } from "../store/toastStore";

export function AlertModal() {
  const modal = useToastStore((s) => s.modal);
  const close = useToastStore((s) => s.closeModal);

  useEffect(() => {
    if (!modal) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [modal, close]);

  if (!modal) return null;

  return (
    <div
      className={"alert-modal-backdrop alert-modal-" + modal.level}
      role="alertdialog"
      aria-modal="true"
      onClick={close}
    >
      <div className="alert-modal" onClick={(e) => e.stopPropagation()}>
        <div className="alert-modal-siren" aria-hidden="true">
          <span className="alert-modal-icon">⚠</span>
        </div>
        <h2 className="alert-modal-title">{modal.title}</h2>
        {modal.body && <p className="alert-modal-body">{modal.body}</p>}
        <div className="alert-modal-actions">
          <button type="button" className="alert-modal-dismiss" onClick={close}>
            확인 (ESC)
          </button>
        </div>
      </div>
    </div>
  );
}
