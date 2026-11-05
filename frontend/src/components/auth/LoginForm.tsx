import { useEffect, useState, type FormEvent } from "react";
import Button from "../ui/Button";

const savedEmployeeNoKey = "weeing-saved-employee-no";

function readSavedEmployeeNo() {
  try {
    return localStorage.getItem(savedEmployeeNoKey) || "";
  } catch {
    return "";
  }
}

export function EyeIcon({ off = false }: { off?: boolean }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.6" />
      {off && (
        <path
          d="M4 4l16 16"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
        />
      )}
    </svg>
  );
}

export default function LoginForm({
  onLogin,
  onForgotPassword,
  sessionError,
}: {
  onLogin: (id: string, password: string) => Promise<void>;
  onForgotPassword: () => void;
  sessionError?: string;
}) {
  const [savedEmployeeNo] = useState(readSavedEmployeeNo);
  const [id, setId] = useState(savedEmployeeNo);
  const [rememberEmployeeNo, setRememberEmployeeNo] = useState(
    Boolean(savedEmployeeNo),
  );
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  useEffect(() => {
    try {
      if (rememberEmployeeNo && id.trim()) {
        localStorage.setItem(savedEmployeeNoKey, id.trim());
      } else {
        localStorage.removeItem(savedEmployeeNoKey);
      }
    } catch {
      // 브라우저 저장소를 사용할 수 없어도 로그인은 계속할 수 있다.
    }
  }, [id, rememberEmployeeNo]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await onLogin(id.trim(), password);
    } catch (failure) {
      setError(
        failure instanceof Error ? failure.message : "로그인에 실패했습니다.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="login-form" onSubmit={handleSubmit}>
      <div className="login-field">
        <label htmlFor="login-id">사번</label>
        <input
          id="login-id"
          value={id}
          onChange={(event) => {
            setId(event.target.value);
            setError("");
          }}
          placeholder="사번을 입력해 주세요"
          autoComplete="username"
          aria-invalid={Boolean(error)}
          disabled={busy}
          required
        />
      </div>
      <div className="login-field">
        <label htmlFor="login-password">비밀번호</label>
        <div className="login-password">
          <input
            id="login-password"
            type={showPassword ? "text" : "password"}
            value={password}
            onChange={(event) => {
              setPassword(event.target.value);
              setError("");
            }}
            placeholder="비밀번호를 입력해 주세요"
            autoComplete="current-password"
            aria-invalid={Boolean(error)}
            disabled={busy}
            required
          />
          <button
            type="button"
            onClick={() => setShowPassword(!showPassword)}
            aria-label={showPassword ? "비밀번호 숨기기" : "비밀번호 보기"}
          >
            <EyeIcon off={showPassword} />
          </button>
        </div>
      </div>
      {(error || sessionError) && (
        <p className="login-form__error" role="alert">
          {error || sessionError}
        </p>
      )}
      <div className="login-options">
        <label>
          <input
            type="checkbox"
            checked={rememberEmployeeNo}
            onChange={(event) => setRememberEmployeeNo(event.target.checked)}
            disabled={busy}
          />{" "}
          사번 저장
        </label>
        <button
          type="button"
          className="login-options__link"
          onClick={onForgotPassword}
        >
          비밀번호 찾기
        </button>
      </div>
      <Button variant="primary" type="submit" disabled={busy}>
        {busy ? "로그인 중…" : "로그인"}
      </Button>
    </form>
  );
}
