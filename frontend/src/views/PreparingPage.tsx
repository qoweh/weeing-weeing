import Button from '../components/ui/Button'
import PageTitle from '../components/ui/PageTitle'
import './PreparingPage.css'

export default function PreparingPage({
  onNavigate,
}: {
  onNavigate?: (page: string) => void
}) {
  return (
    <div className="preparing-page">
      <PageTitle>대시보드</PageTitle>
      <div className="preparing" aria-label="페이지 준비 중">
        <section className="preparing__card">
          <div className="preparing__icon" aria-hidden="true">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <circle cx="12" cy="12" r="9" />
              <path d="M12 7v5l3 2" />
            </svg>
          </div>
          <span className="preparing__badge">COMING SOON</span>
          <h2 className="preparing__title">페이지 준비 중입니다</h2>
          <p className="preparing__text">
            더 나은 화면으로 찾아뵙기 위해 준비하고 있습니다.
            <br />
            조금만 기다려 주세요.
          </p>
          <Button variant="primary" onClick={() => onNavigate?.('incidents')}>
            이상 현황으로 이동
          </Button>
        </section>
      </div>
    </div>
  )
}
