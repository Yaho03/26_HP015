import { useToastStore } from "../store/toastStore";

export function AlertModal() {
  const modal = useToastStore((s) => s.modal);

  if (!modal) return null;

  return (
    <aside
      className={"alert-modal alert-modal--persistent alert-modal-" + modal.level}
      role="alert"
      aria-live="assertive"
    >
      <div className="alert-modal__accent" aria-hidden="true" />
      <div className="alert-modal-siren" aria-hidden="true">
        !
      </div>
      <div className="alert-modal-content">
        <p className="alert-modal-eyebrow">ACTIVE SAFETY ALERT / L3</p>
        <h2 className="alert-modal-title">{modal.title}</h2>
        {modal.body && <p className="alert-modal-body">{modal.body}</p>}
        <p className="alert-modal-persistent-note">경보가 해제될 때까지 표시됩니다</p>
      </div>
    </aside>
  );
}
