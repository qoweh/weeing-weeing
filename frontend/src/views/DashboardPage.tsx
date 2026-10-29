import MetricCard from '../components/dashboard/MetricCard'
import ChartCard from '../components/dashboard/ChartCard'
import IncidentTable from '../components/dashboard/IncidentTable'
import AssistantPanel from '../components/dashboard/AssistantPanel'
import '../components/dashboard/dashboard.scss'
const metrics = [
  {
    title: '모니터링 설비',
    value: '1',
    unit: '대',
    note: '확인 대상 설비',
    tone: 'neutral',
    icon: '▦',
  },
  {
    title: '진행 중인 이상',
    value: '2',
    unit: '건',
    note: '담당자 확인 필요',
    tone: 'warning',
    icon: '◉',
  },
  {
    title: '검토 완료',
    value: '8',
    unit: '건',
    note: '최근 7일 기준',
    tone: 'success',
    icon: '✓',
  },
  {
    title: '연결 상태',
    value: '—',
    unit: '',
    note: '실제 연결 전',
    tone: 'neutral',
    icon: '⌁',
  },
]
const bars = [32, 51, 40, 78, 48, 64, 38]
export default function DashboardPage() {
  return (
    <div className="dashboard">
      <div className="dashboard__heading">
        <div>
          <div className="eyebrow">OVERVIEW</div>
          <h1>설비 대시보드</h1>
          <p>설비 상태와 최근 이상 현황을 한눈에 확인하세요.</p>
        </div>
        <div className="period-label">
          <span aria-hidden="true">◷</span> 최근 7일 <span>·</span> 예시 데이터
        </div>
      </div>
      <div className="sample-banner">
        <span aria-hidden="true">ⓘ</span>
        <span>
          <strong>화면 미리보기</strong> · 아래 수치와 사건은 예시이며 실제
          설비와 연결되어 있지 않습니다.
        </span>
      </div>
      <div className="dashboard__grid">
        <div className="dashboard__column">
          <div className="metrics">
            {metrics.map((item) => (
              <MetricCard key={item.title} {...item} />
            ))}
          </div>
          <ChartCard
            title="센서 추이"
            description="시간에 따른 센서값 변화"
            className="trend"
          >
            <div className="trend__summary">
              <span>센서값 예시</span>
              <strong>
                — <small>단위 미정</small>
              </strong>
              <p>데이터 연동 전 미리보기</p>
            </div>
            <div className="trend__graph">
              <svg
                viewBox="0 0 600 190"
                role="img"
                aria-label="화면 예시를 위한 임의의 센서 추이 그래프"
                preserveAspectRatio="none"
              >
                <defs>
                  <linearGradient id="chart-fill" x1="0" y1="0" x2="0" y2="1">
                    <stop
                      offset="0%"
                      stopColor="var(--primary)"
                      stopOpacity=".22"
                    />
                    <stop
                      offset="100%"
                      stopColor="var(--primary)"
                      stopOpacity="0"
                    />
                  </linearGradient>
                </defs>
                <path
                  className="grid-line"
                  d="M0 35H600 M0 85H600 M0 135H600 M0 185H600"
                />
                <path
                  d="M0 140 L45 128 L90 135 L135 105 L180 116 L225 92 L270 108 L315 70 L360 82 L405 48 L450 67 L495 42 L540 55 L600 28 L600 185 L0 185 Z"
                  fill="url(#chart-fill)"
                />
                <path
                  d="M0 140 L45 128 L90 135 L135 105 L180 116 L225 92 L270 108 L315 70 L360 82 L405 48 L450 67 L495 42 L540 55 L600 28"
                  fill="none"
                  stroke="var(--primary)"
                  strokeWidth="3"
                  vectorEffect="non-scaling-stroke"
                />
              </svg>
              <div className="graph-labels">
                <span>7일 전</span>
                <span>5일 전</span>
                <span>3일 전</span>
                <span>오늘</span>
              </div>
            </div>
          </ChartCard>
          <IncidentTable />
        </div>
        <div className="dashboard__column">
          <ChartCard
            title="요일별 이상 현황"
            description="최근 7일의 발생 현황"
          >
            <div
              className="bar-chart"
              role="img"
              aria-label="화면 예시를 위한 임의의 요일별 막대그래프"
            >
              {bars.map((height, i) => (
                <div className="bar-chart__item" key={i}>
                  <div
                    className={`bar-chart__bar ${i === 3 ? 'bar-chart__bar--active' : ''}`}
                    style={{ height: `${height}%` }}
                  />
                  <span>{['월', '화', '수', '목', '금', '토', '일'][i]}</span>
                </div>
              ))}
            </div>
          </ChartCard>
          <ChartCard title="사건 처리 현황" description="최근 7일 기준">
            <div className="status-list">
              <div>
                <span>
                  <i className="status-dot status-dot--warning" />
                  확인 대기
                </span>
                <strong>1건</strong>
              </div>
              <div>
                <span>
                  <i className="status-dot status-dot--primary" />
                  검토 중
                </span>
                <strong>1건</strong>
              </div>
              <div>
                <span>
                  <i className="status-dot status-dot--success" />
                  검토 완료
                </span>
                <strong>8건</strong>
              </div>
            </div>
          </ChartCard>
          <AssistantPanel />
        </div>
      </div>
    </div>
  )
}
