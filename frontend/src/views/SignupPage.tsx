import SignupForm from '../components/auth/SignupForm'
import '../components/auth/login.scss'
import '../components/auth/signup.scss'

export default function SignupPage({ onLogin }: { onLogin: () => void }) {
  return (
    <main className="login-page signup-page">
      <div className="login-brand">
        <span className="login-brand__mark">W</span>
        <span>
          위잉위잉<small>Equipment AI</small>
        </span>
      </div>
      <section
        className="login-card signup-card"
        aria-labelledby="signup-title"
      >
        <p className="login-card__eyebrow">CREATE ACCOUNT</p>
        <h1 id="signup-title">회원가입</h1>
        <p className="login-card__description">
          계정 정보를 입력하고 서비스를 시작하세요.
        </p>
        <SignupForm />
        <div className="login-card__contact">
          이미 계정이 있으신가요?{' '}
          <button className="auth-link" type="button" onClick={onLogin}>
            로그인
          </button>
        </div>
      </section>
      <footer className="login-footer">© 위잉위잉 · Equipment AI</footer>
    </main>
  )
}
