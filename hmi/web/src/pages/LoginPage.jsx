import LoginForm from '../components/auth/LoginForm.jsx'
import '../components/auth/login.scss'

export default function LoginPage({ onLogin, onSignup, error }) {
  return <main className="login-page"><section className="login-card" aria-labelledby="login-title"><p className="login-card__eyebrow">WELCOME BACK</p><h1 id="login-title">로그인</h1><p className="login-card__description">계정 정보를 입력하고 서비스를 시작하세요.</p><LoginForm onLogin={onLogin} sessionError={error} /><div className="login-card__contact">계정이 필요하신가요? <button className="auth-link" type="button" onClick={onSignup}>회원가입</button></div></section><footer className="login-footer">© 위잉위잉 · Equipment AI</footer></main>
}
