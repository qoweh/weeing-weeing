import Card from '../ui/Card'
export default function AssistantPanel() {
  return (
    <Card className="assistant">
      <div className="card-heading">
        <div>
          <h2>AI 어시스턴트</h2>
          <p>근거를 바탕으로 설비 정보를 탐색합니다</p>
        </div>
        <span className="card-heading__sample">준비 중</span>
      </div>
      <div className="assistant__body">
        <div className="assistant__orb" aria-hidden="true">
          ✦
        </div>
        <strong>무엇을 도와드릴까요?</strong>
        <p>
          이상 사건과 정비 문서를 바탕으로
          <br />
          필요한 정보를 확인할 수 있어요.
        </p>
      </div>
      <div className="assistant__placeholder">
        AI 질의응답 기능을 준비하고 있습니다 <span aria-hidden="true">↗</span>
      </div>
      <p className="assistant__note">AI의 제안과 근거는 담당자가 검토합니다.</p>
    </Card>
  )
}
