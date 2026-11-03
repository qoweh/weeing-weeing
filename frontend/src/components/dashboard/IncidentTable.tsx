import Card from '../ui/Card'
import Badge from '../ui/Badge'
const rows = [
  [
    'INC-024',
    '컨베이어 1호기',
    '진동 수치 확인',
    '10:32',
    '확인 대기',
    'warning',
  ],
  [
    'INC-023',
    '컨베이어 1호기',
    '온도 추이 확인',
    '09:15',
    '검토 중',
    'neutral',
  ],
  [
    'INC-022',
    '컨베이어 1호기',
    '센서 신호 확인',
    '어제 16:40',
    '검토 완료',
    'success',
  ],
]
export default function IncidentTable() {
  return (
    <Card className="incident-card">
      <div className="card-heading">
        <div>
          <h2>최근 이상 사건</h2>
          <p>최근 접수된 사건을 확인하세요</p>
        </div>
        <span className="card-heading__sample">예시</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>사건 번호</th>
              <th>설비</th>
              <th>내용</th>
              <th>발생 시각</th>
              <th>상태</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([id, equipment, detail, time, status, tone]) => (
              <tr key={id}>
                <td className="table-id">{id}</td>
                <td>{equipment}</td>
                <td>{detail}</td>
                <td className="table-muted">{time}</td>
                <td>
                  <Badge tone={tone}>{status}</Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="table-footnote">
        표시된 사건은 화면 구성을 위한 예시입니다.
      </p>
    </Card>
  )
}
