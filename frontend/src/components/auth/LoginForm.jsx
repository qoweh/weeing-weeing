import { useState } from 'react'
import Button from '../ui/Button.jsx'

export default function LoginForm({ onLogin }) {
  const [id, setId] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [showPassword, setShowPassword] = useState(false)

  function handleSubmit(event) {
    event.preventDefault()
    if (id === '1' && password === '1') onLogin()
    else setError('아이디 또는 비밀번호가 올바르지 않습니다.')
  }

  return <form className="login-form" onSubmit={handleSubmit}><div className="login-field"><label htmlFor="login-id">이메일</label><input id="login-id" value={id} onChange={(event) => { setId(event.target.value); setError('') }} placeholder="이메일을 입력해 주세요" autoComplete="username" required /></div><div className="login-field"><label htmlFor="login-password">비밀번호</label><div className="login-password"><input id="login-password" type={showPassword ? 'text' : 'password'} value={password} onChange={(event) => { setPassword(event.target.value); setError('') }} placeholder="비밀번호를 입력해 주세요" autoComplete="current-password" required /><button type="button" onClick={() => setShowPassword(!showPassword)} aria-label={showPassword ? '비밀번호 숨기기' : '비밀번호 보기'}>◉</button></div></div><div className="login-options"><label title="준비 중"><input type="checkbox" disabled /> 로그인 상태 유지</label><span title="준비 중">비밀번호 찾기</span></div>{error && <p className="login-form__error" role="alert">{error}</p>}<Button variant="primary" type="submit">로그인</Button></form>
}
