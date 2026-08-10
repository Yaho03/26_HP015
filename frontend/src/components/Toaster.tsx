import { useEffect } from "react";
import { useToastStore, toastTtlMs } from "../store/toastStore";
import type { ToastItem } from "../store/toastStore";

function ToastRow({ toast }: { toast: ToastItem }) {
  const dismiss = useToastStore((s) => s.dismiss);
  const ttl = toastTtlMs(toast.level);

  useEffect(() => {
    if (ttl <= 0) return;
    const id = setTimeout(() => dismiss(toast.id), ttl);
    return () => clearTimeout(id);
  }, [ttl, toast.id, dismiss]);

  return (
    <div className={"toast toast-" + toast.level} role="status">
      <div className="toast-content">
        <div className="toast-title">{toast.title}</div>
        {toast.body && <div className="toast-body">{toast.body}</div>}
      </div>
      <button
        type="button"
        className="toast-close"
        onClick={() => dismiss(toast.id)}
        aria-label="dismiss"
      >
        ×
      </button>
    </div>
  );
}

export function Toaster() {
  const toasts = useToastStore((s) => s.toasts);
  if (toasts.length === 0) return null;
  return (
    <div className="toaster" aria-live="polite">
      {toasts.map((t) => (
        <ToastRow key={t.id} toast={t} />
      ))}
    </div>
  );
}
