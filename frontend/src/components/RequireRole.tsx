import type { ReactNode } from "react";
import { hasRole, useAuthStore } from "../store/authStore";

interface RequireRoleProps {
  min: "viewer" | "supervisor" | "admin";
  children: ReactNode;
  fallback?: ReactNode;
}

/**
 * 역할 게이팅 래퍼 (AUTH-8). UI 숨김은 편의일 뿐이다 — 서버 측 권한이
 * 정본이므로 직접 API 호출은 여전히 403 으로 거부된다.
 */
export function RequireRole({ min, children, fallback = null }: RequireRoleProps) {
  const user = useAuthStore((s) => s.user);
  if (!hasRole(user?.role, min)) return <>{fallback}</>;
  return <>{children}</>;
}
