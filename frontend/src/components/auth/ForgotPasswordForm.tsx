import { useState, type FormEvent } from "react";
import Button from "../ui/Button";

export default function ForgotPasswordForm() {
  const [employeeNo, setEmployeeNo] = useState("");
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // 재설정 API가 아직 없어 안내만 표시한다.
    setMessage("비밀번호 찾기 서비스는 준비 중입니다.");
  }

  return (
    <form className="login-form" onSubmit={handleSubmit}>
      <div className="login-field">
        <label htmlFor="forgot-id">사번</label>
        <input
          id="forgot-id"
          value={employeeNo}
          onChange={(event) => {
            setEmployeeNo(event.target.value);
            setMessage("");
          }}
          placeholder="사번을 입력해 주세요"
          autoComplete="username"
          required
        />
      </div>
      <div className="login-field">
        <label htmlFor="forgot-email">이메일</label>
        <input
          id="forgot-email"
          type="email"
          value={email}
          onChange={(event) => {
            setEmail(event.target.value);
            setMessage("");
          }}
          placeholder="가입한 이메일을 입력해 주세요"
          autoComplete="email"
          required
        />
      </div>
      <p className="login-form__hint">
        계정에 등록된 이메일로 재설정 링크를 보냅니다.
      </p>
      {message && (
        <p className="login-form__error" role="status">
          {message}
        </p>
      )}
      <Button variant="primary" type="submit">
        재설정 안내 받기
      </Button>
    </form>
  );
}
