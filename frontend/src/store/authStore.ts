import { create } from "zustand";

export type Role = "admin" | "supervisor" | "viewer";

export interface AuthUser {
  id: number;
  username: string;
  display_name: string;
  role: Role;
  must_change_password: boolean;
}

export type AuthStatus = "booting" | "authenticated" | "unauthenticated";

interface AuthStore {
  user: AuthUser | null;
  status: AuthStatus;

  setUser: (user: AuthUser | null) => void;
  expire: () => void;
}

export const useAuthStore = create<AuthStore>((set) => ({
  user: null,
  status: "booting",

  setUser: (user) => set({ user, status: user ? "authenticated" : "unauthenticated" }),

  // 401/WS 1008 — 세션이 끊겼다. 사용자 정보를 지우고 로그인으로 되돌린다.
  expire: () => set({ user: null, status: "unauthenticated" }),
}));

/** 메뉴 게이팅용 최소 역할 비교. 서버 권한이 정본 — 이것은 UX 용도다. */
export function hasRole(role: Role | undefined | null, min: Role): boolean {
  const order: Record<Role, number> = { viewer: 0, supervisor: 1, admin: 2 };
  if (!role) return false;
  return order[role] >= order[min];
}
