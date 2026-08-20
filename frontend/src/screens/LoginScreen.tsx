import { useState, type FormEvent } from "react";
import { login } from "../services/authApi";
import { useAuthStore } from "../store/authStore";

export function LoginScreen() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const setUser = useAuthStore((s) => s.setUser);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(username, password);
      // 성공 — setUser 가 이미 불렸으므로 App 이 자동으로 전환한다.
    } catch {
      // 서버는 계정 존재 여부를 응답으로 구분하지 않는다 (FR-609).
      // 여기서도 동일 문구만 보여준다.
      setError("사용자 이름 또는 비밀번호가 올바르지 않습니다");
      setUser(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-screen">
      <form className="login-card" onSubmit={onSubmit}>
        <h1 className="login-title">HP015 Console</h1>
        <p className="login-subtitle">밀폐공간 모니터링 시스템</p>

        <label className="login-field">
          <span>사용자 이름</span>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoFocus
            required
          />
        </label>

        <label className="login-field">
          <span>비밀번호</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>

        {error && <p className="login-error" role="alert">{error}</p>}

        <button type="submit" className="login-submit" disabled={busy || !username || !password}>
          {busy ? "확인 중…" : "로그인"}
        </button>
      </form>
    </div>
  );
}
