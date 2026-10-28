import LoginForm from '../components/auth/LoginForm.jsx'
import '../components/auth/login.scss'

export default function LoginPage({ onLogin, onCancel }) {
  return <main className="login-page"><section className="login-card" aria-labelledby="login-title"><p className="login-card__eyebrow">WELCOME BACK</p><h1 id="login-title">로그인</h1><p className="login-card__description">계정 정보를 입력하고 서비스를 시작하세요.</p><LoginForm onLogin={onLogin} /><div className="login-card__contact">계정이 필요하신가요? <strong>관리자에게 문의</strong></div></section><footer className="login-footer">© 위잉위잉 · Equipment AI</footer><button className="login-back" type="button" onClick={onCancel}>대시보드로 돌아가기</button></main>
}
