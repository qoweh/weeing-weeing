import { useState } from 'react'
import Button from '../ui/Button.jsx'

export default function SignupForm() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [visible, setVisible] = useState(false)
  const [confirmationVisible, setConfirmationVisible] = useState(false)
  const [message, setMessage] = useState('')

  function handleSubmit(event) {
    event.preventDefault()
    if (password !== confirmation) {
      setMessage('비밀번호가 일치하지 않습니다.')
      return
    }
    setMessage('회원가입 서비스는 준비 중입니다.')
  }

  return <form className="login-form signup-form" onSubmit={handleSubmit}>
    <div className="login-field"><label htmlFor="signup-email">이메일</label><input id="signup-email" type="email" autoComplete="email" value={email} onChange={(event) => { setEmail(event.target.value); setMessage('') }} placeholder="이메일을 입력해 주세요" required /></div>
    <div className="login-field"><label htmlFor="signup-password">비밀번호</label><div className="login-password"><input id="signup-password" type={visible ? 'text' : 'password'} autoComplete="new-password" value={password} onChange={(event) => { setPassword(event.target.value); setMessage('') }} placeholder="비밀번호를 입력해 주세요" required /><button type="button" onClick={() => setVisible(!visible)} aria-label={visible ? '비밀번호 숨기기' : '비밀번호 보기'}>◉</button></div></div>
    <div className="login-field"><label htmlFor="signup-confirmation">비밀번호 확인</label><div className="login-password"><input id="signup-confirmation" type={confirmationVisible ? 'text' : 'password'} autoComplete="new-password" value={confirmation} onChange={(event) => { setConfirmation(event.target.value); setMessage('') }} placeholder="비밀번호를 다시 입력해 주세요" required /><button type="button" onClick={() => setConfirmationVisible(!confirmationVisible)} aria-label={confirmationVisible ? '비밀번호 확인 숨기기' : '비밀번호 확인 보기'}>◉</button></div></div>
    {message && <p className="login-form__error" role="status">{message}</p>}
    <Button variant="primary" type="submit">회원가입</Button>
  </form>
}
