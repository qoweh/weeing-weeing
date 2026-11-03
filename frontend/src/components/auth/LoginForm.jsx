import { useState } from 'react'
import Button from '../ui/Button.jsx'

export default function LoginForm({ onLogin, sessionError }) {
  const [id, setId] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [showPassword, setShowPassword] = useState(false)

  async function handleSubmit(event) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError('')
    try {
      await onLogin(id.trim(), password)
    } catch (failure) {
      setError(failure.message)
    } finally {
      setBusy(false)
    }
  }

  return <form className="login-form" onSubmit={handleSubmit}><div className="login-field"><label htmlFor="login-id">사번</label><input id="login-id" value={id} onChange={(event) => { setId(event.target.value); setError('') }} placeholder="사번을 입력해 주세요" autoComplete="username" disabled={busy} required /></div><div className="login-field"><label htmlFor="login-password">비밀번호</label><div className="login-password"><input id="login-password" type={showPassword ? 'text' : 'password'} value={password} onChange={(event) => { setPassword(event.target.value); setError('') }} placeholder="비밀번호를 입력해 주세요" autoComplete="current-password" disabled={busy} required /><button type="button" onClick={() => setShowPassword(!showPassword)} aria-label={showPassword ? '비밀번호 숨기기' : '비밀번호 보기'}>◉</button></div></div><div className="login-options"><label title="준비 중"><input type="checkbox" disabled /> 로그인 상태 유지</label><span title="준비 중">비밀번호 찾기</span></div>{(error || sessionError) && <p className="login-form__error" role="alert">{error || sessionError}</p>}<Button variant="primary" type="submit" disabled={busy}>{busy ? "로그인 중…" : "로그인"}</Button></form>
}
