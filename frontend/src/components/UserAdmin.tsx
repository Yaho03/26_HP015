import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  createUser,
  fetchUsers,
  resetUserPassword,
  updateUser,
  type AdminUser,
} from "../services/api";
import { ApiError } from "../services/fetchWithAuth";

const ROLE_LABEL: Record<AdminUser["role"], string> = {
  admin: "관리자",
  supervisor: "감독자",
  viewer: "열람자",
};

/** 설정 > 사용자 탭 (admin 전용 — AUTH-10, 이슈 #140). */
export function UserAdmin() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [tempPassword, setTempPassword] = useState<{ username: string; password: string } | null>(
    null,
  );
  const [form, setForm] = useState({
    username: "",
    password: "",
    role: "viewer" as AdminUser["role"],
  });

  const reload = useCallback(async () => {
    try {
      setUsers(await fetchUsers());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "목록 조회 실패");
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await createUser(form);
      setForm({ username: "", password: "", role: "viewer" });
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "생성 실패");
    }
  }

  async function toggleActive(user: AdminUser) {
    try {
      await updateUser(user.id, { is_active: !user.is_active });
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "상태 변경 실패");
    }
  }

  async function changeRole(user: AdminUser, role: AdminUser["role"]) {
    try {
      await updateUser(user.id, { role });
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "역할 변경 실패");
    }
  }

  async function resetPassword(user: AdminUser) {
    try {
      const { temporary_password } = await resetUserPassword(user.id);
      setTempPassword({ username: user.username, password: temporary_password });
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "초기화 실패");
    }
  }

  return (
    <section className="user-admin">
      <h3 className="user-admin-title">계정 관리</h3>
      <p className="user-admin-sub">
        생성·역할 변경·비밀번호 초기화는 감사 로그에 기록됩니다. 임시 비밀번호는 초기화 직후 한 번만
        표시됩니다.
      </p>

      <form className="user-admin-form" onSubmit={onSubmit}>
        <input
          placeholder="사용자 이름"
          value={form.username}
          onChange={(e) => setForm({ ...form, username: e.target.value })}
          required
          minLength={3}
        />
        <input
          type="password"
          placeholder="초기 비밀번호 (8자 이상)"
          value={form.password}
          onChange={(e) => setForm({ ...form, password: e.target.value })}
          required
          minLength={8}
        />
        <select
          value={form.role}
          onChange={(e) => setForm({ ...form, role: e.target.value as AdminUser["role"] })}
        >
          <option value="viewer">열람자</option>
          <option value="supervisor">감독자</option>
          <option value="admin">관리자</option>
        </select>
        <button type="submit">생성</button>
      </form>

      {error && (
        <p className="user-admin-error" role="alert">
          {error}
        </p>
      )}

      {tempPassword && (
        <div className="user-admin-temp" role="status">
          <strong>{tempPassword.username}</strong> 임시 비밀번호:{" "}
          <code>{tempPassword.password}</code>
          <button type="button" onClick={() => setTempPassword(null)}>
            닫기
          </button>
        </div>
      )}

      <table className="user-admin-table">
        <thead>
          <tr>
            <th>사용자</th>
            <th>역할</th>
            <th>상태</th>
            <th>잠금</th>
            <th>관리</th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id} className={u.is_active ? "" : "user-admin-row-inactive"}>
              <td>
                {u.username}
                {u.must_change_password && <span className="user-admin-flag">변경 필요</span>}
              </td>
              <td>
                <select
                  value={u.role}
                  onChange={(e) => void changeRole(u, e.target.value as AdminUser["role"])}
                >
                  <option value="viewer">{ROLE_LABEL.viewer}</option>
                  <option value="supervisor">{ROLE_LABEL.supervisor}</option>
                  <option value="admin">{ROLE_LABEL.admin}</option>
                </select>
              </td>
              <td>{u.is_active ? "활성" : "비활성"}</td>
              <td>
                {u.locked_until
                  ? `잠금 (${new Date(u.locked_until).toLocaleTimeString()})`
                  : u.failed_login_attempts > 0
                    ? `실패 ${u.failed_login_attempts}회`
                    : "—"}
              </td>
              <td>
                <button type="button" onClick={() => void toggleActive(u)}>
                  {u.is_active ? "비활성화" : "활성화"}
                </button>
                <button type="button" onClick={() => void resetPassword(u)}>
                  비밀번호 초기화
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
