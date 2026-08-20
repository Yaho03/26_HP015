import { create } from "zustand";
import type { AlertLevel } from "../types";

export interface ToastItem {
  id: string;
  level: AlertLevel;
  title: string;
  body?: string;
  created_at: number;
}

interface ToastStore {
  toasts: ToastItem[];
  modal: { alert_key: string; level: AlertLevel; title: string; body?: string } | null;
  push: (toast: Omit<ToastItem, "id" | "created_at">) => void;
  dismiss: (id: string) => void;
  openModal: (modal: { alert_key: string; level: AlertLevel; title: string; body?: string }) => void;
  closeModal: () => void;
}

function uid(): string {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export const useToastStore = create<ToastStore>((set) => ({
  toasts: [],
  modal: null,
  push: (toast) =>
    set((s) => ({
      toasts: [...s.toasts, { ...toast, id: uid(), created_at: Date.now() }],
    })),
  dismiss: (id) =>
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
  openModal: (modal) => set({ modal }),
  closeModal: () => set({ modal: null }),
}));

const TOAST_TTL_MS: Record<AlertLevel, number> = {
  normal: 3000,
  level1_caution: 5000,
  level2_warning: 8000,
  level3_critical: 0,
};

export function toastTtlMs(level: AlertLevel): number {
  return TOAST_TTL_MS[level];
}
