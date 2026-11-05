import AuthHero from "../components/auth/AuthHero";
import ForgotPasswordForm from "../components/auth/ForgotPasswordForm";
import "../components/auth/login.scss";

export default function ForgotPasswordPage({
  onLogin,
}: {
  onLogin: () => void;
}) {
  return (
    <main className="login-page">
      <AuthHero />
      <section className="login-card" aria-labelledby="forgot-title">
        <p className="login-card__eyebrow">RESET PASSWORD</p>
        <h1 id="forgot-title">비밀번호 찾기</h1>
        <p className="login-card__description">
          가입한 사번과 이메일을 입력하면 비밀번호 재설정 안내를 보내 드립니다.
        </p>
        <ForgotPasswordForm />
        <div className="login-card__contact">
          <button
            className="auth-link auth-link--back"
            type="button"
            onClick={onLogin}
          >
            로그인으로 돌아가기
          </button>
        </div>
      </section>
      <footer className="login-footer">© 위잉위잉 · Equipment AI</footer>
    </main>
  );
}
