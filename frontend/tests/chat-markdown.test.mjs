import test from 'node:test'
import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ChatMarkdown from '../src/components/chat/ChatMarkdown.js'

const render = (text) =>
  renderToStaticMarkup(createElement(ChatMarkdown, null, text))

test('제목·강조·목록·표·코드 블록을 마크다운으로 렌더링한다', () => {
  const html = render(
    '## 확인 결과\n\n**주의**\n\n- 센서 확인\n- 값 확인\n\n| 센서 | 값 |\n| --- | --- |\n| 온도 | 86℃ |\n\n```text\ncode <tag>\n```',
  )
  assert.match(html, /<h4>확인 결과<\/h4>/)
  assert.match(html, /<strong>주의<\/strong>/)
  assert.match(html, /<ul>/)
  assert.match(html, /<table>/)
  assert.match(html, /<pre><code/)
  assert.match(html, /code &lt;tag&gt;/)
})

test('원시 HTML·이미지 로드·모델이 만든 링크를 실행하지 않는다', () => {
  const html = render(
    '<script>alert(1)</script>\n\n<img src="https://evil.test/pixel">\n\n![추적](https://evil.test/pixel)\n\n[위험](javascript:alert(1)) [참고](https://evil.test)',
  )
  assert.doesNotMatch(html, /<script|<img|href=|src=/)
  assert.match(html, /위험/)
  assert.match(html, /참고/)
})

test('단일 개행을 실제 줄바꿈으로 보존한다', () => {
  const html = render('원인 설명\n점검 방법\n처리 결과')
  assert.equal((html.match(/<br\/?\s*>/g) || []).length, 2)
})
