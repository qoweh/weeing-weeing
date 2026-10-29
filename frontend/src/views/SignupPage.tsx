import SignupForm from '../components/auth/SignupForm'
import '../components/auth/login.scss'
import '../components/auth/signup.scss'

export default function SignupPage({
  onLogin,
  animate,
  exiting,
  cardRef,
}: {
  onLogin?: () => void
  animate?: boolean
  exiting?: boolean
  cardRef?: React.Ref<HTMLElement>
}) {
  return (
    <main className="login-page signup-page">
      <section
        ref={cardRef}
        className={`login-card signup-card${animate ? ' auth-card--to-signup' : ''}${exiting ? ' auth-card--exiting' : ''}`}
        aria-labelledby="signup-title"
      >
        <div className="auth-card__content">
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
        </div>
      </section>
      <footer className="login-footer">© 위잉위잉 · Equipment AI</footer>
    </main>
  )
}
