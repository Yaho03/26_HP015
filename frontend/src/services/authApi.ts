import type { AuthUser } from "../store/authStore";
import { useAuthStore } from "../store/authStore";
import { fetchApi } from "./fetchWithAuth";

export interface LoginResult {
  user: AuthUser;
  csrf_token: string;
}

export async function login(username: string, password: string): Promise<LoginResult> {
  const { user, csrf_token } = await fetchApi<LoginResult>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  useAuthStore.getState().setUser(user);
  return { user, csrf_token };
}

export async function logout(): Promise<void> {
  try {
    await fetchApi("/api/auth/logout", { method: "POST", csrf: true });
  } finally {
    // 서버 폐기 실패(이미 만료 등)여도 클라이언트 상태는 초기화한다.
    useAuthStore.getState().setUser(null);
  }
}

export async function fetchMe(): Promise<AuthUser | null> {
  const user = await fetchApi<AuthUser>("/api/auth/me");
  useAuthStore.getState().setUser(user);
  return user;
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  await fetchApi("/api/auth/password", {
    method: "POST",
    csrf: true,
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
  useAuthStore.getState().setUser(null);
}
