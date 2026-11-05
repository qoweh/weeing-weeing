import type { Analysis, ReportIncident } from './ReportForm'
import './ReportForm.css'

function evidenceLabel(item: NonNullable<Analysis['evidence']>[number]) {
  if (!item.page && !item.title) return item.citation
  return [
    item.title || item.doc_id || '문서',
    item.doc_version && `v${item.doc_version}`,
    item.page && `PDF ${item.page}쪽`,
    item.section,
  ]
    .filter(Boolean)
    .join(' · ')
}

function readableText(text: string, incident?: ReportIncident | null) {
  const header = `사건:\n사건 ID: ${incident?.incident_id}`
  const display =
    incident?.incident_id && (text === header || text.startsWith(`${header}\n`))
      ? `사건번호: ${incident.incident_number || '확인되지 않음'}${text.slice(header.length)}`
      : text
  const fields: Record<string, string> = {
    motor_housing_temp_c: '모터 외함 온도',
    rpm: '모터 회전 속도',
    dc_input_current_a: 'DC 입력 전류',
    dc_bus_voltage_v: 'DC 버스 전압',
    infeed_present: '입구 센서',
    outfeed_present: '출구 센서',
    de_vibration_rms_g: '구동측 진동 RMS',
    nde_vibration_rms_g: '반구동측 진동 RMS',
    de_kurtosis: '구동측 첨도',
    nde_kurtosis: '반구동측 첨도',
  }
  const statistics: Record<string, string> = {
    min: '최솟값',
    max: '최댓값',
    mean: '평균',
    first: '처음값',
    last: '마지막값',
    delta: '변화량',
    valid_count: '유효 표본 수',
    missing_count: '결측 수',
    true_count: '감지 표본 수',
    false_count: '미감지 표본 수',
  }
  return display
    .replace(/\bwindow-(\d+)\b/g, '조회 구간 $1')
    .replace(
      /\b([a-z_]+)\.(min|max|mean|first|last|delta|valid_count|missing_count|true_count|false_count)\b/g,
      (whole, field, stat) =>
        fields[field] ? `${fields[field]} ${statistics[stat]}` : whole,
    )
    .replace(
      /\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\b/g,
      (value) => {
        const date = new Date(value)
        if (Number.isNaN(date.getTime())) return value
        const parts = Object.fromEntries(
          new Intl.DateTimeFormat('ko-KR', {
            timeZone: 'Asia/Seoul',
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hourCycle: 'h23',
          })
            .formatToParts(date)
            .map(({ type, value }) => [type, value]),
        )
        return `${parts.year}. ${parts.month}. ${parts.day}. ${parts.hour}:${parts.minute}:${parts.second}`
      },
    )
}

function Items({
  items,
  ordered = false,
  empty,
}: {
  items?: string[]
  ordered?: boolean
  empty: string
}) {
  if (!items?.length) return <span>{empty}</span>
  const List = ordered ? 'ol' : 'ul'
  return (
    <List className="report-analysis-list">
      {items.map((text, index) => (
        <li key={index}>{text}</li>
      ))}
    </List>
  )
}

export default function ReportAnalysisSection({
  analysis,
  incident = null,
  showTitle = true,
}: {
  analysis: Analysis | null
  incident?: ReportIncident | null
  showTitle?: boolean
}) {
  const ready = analysis?.status === 'OK'
  const message = !analysis
    ? 'AI 초안이 아직 연결되지 않았습니다.'
    : analysis.status === 'INSUFFICIENT_EVIDENCE'
      ? '근거가 부족해 AI 초안 작성을 중단했습니다.'
      : analysis.status === 'OK'
        ? '제시된 원인 후보 없음'
        : 'AI 분석에 실패했습니다. 담당자 확인이 필요합니다.'
  return (
    <section className="report-section">
      {showTitle && (
        <h3 className="report-section-title">
          <span>03</span>AI 분석 및 대응 권고
        </h3>
      )}
      <div className="report-table">
        <div className="report-cell report-cell--wide">
          <strong>추정 원인 및 근거</strong>
          <div className="report-analysis-content">
            {ready && analysis.suspected_causes?.length ? (
              <ul className="report-analysis-list">
                {analysis.suspected_causes.map((item, index) => (
                  <li key={index}>
                    <strong>{item.cause}</strong>
                    {item.likelihood && (
                      <>
                        {' '}
                        ·{' '}
                        {item.likelihood === '미평가'
                          ? '미평가 · 추가 점검 필요'
                          : `가능성 ${item.likelihood}`}
                      </>
                    )}
                    {item.basis &&
                      item.basis.replace(/\r\n/g, '\n').trim() !==
                        analysis.observed_facts
                          ?.replace(/\r\n/g, '\n')
                          .trim() && (
                        <p style={{ whiteSpace: 'pre-wrap' }}>
                          {readableText(item.basis, incident)}
                        </p>
                      )}
                    {item.observations?.length ? (
                      <>
                        <p>
                          <strong>관련 센서 관측</strong>
                        </p>
                        <ul>
                          {item.observations.map((text, observationIndex) => (
                            <li key={observationIndex}>
                              {readableText(text, incident)}
                            </li>
                          ))}
                        </ul>
                      </>
                    ) : null}
                    {item.unconfirmed?.length ? (
                      <>
                        <p>
                          <strong>미확인 사항</strong>
                        </p>
                        <ul>
                          {item.unconfirmed.map((text, unconfirmedIndex) => (
                            <li key={unconfirmedIndex}>
                              {readableText(text, incident)}
                            </li>
                          ))}
                        </ul>
                      </>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : (
              message
            )}
          </div>
        </div>
        <div className="report-cell report-cell--wide">
          <strong>권고 점검 절차</strong>
          <div className="report-analysis-content">
            <Items
              ordered
              items={ready ? analysis.recommended_checks : []}
              empty="제시된 점검 절차 없음"
            />
          </div>
        </div>
        <div className="report-cell report-cell--wide">
          <strong>권고 조치</strong>
          <div className="report-analysis-content">
            <Items
              items={ready ? analysis.recommended_actions : []}
              empty="제시된 조치 없음"
            />
          </div>
        </div>
        <div className="report-cell report-cell--wide">
          <strong>승인이 필요한 조치</strong>
          <div className="report-analysis-content">
            <Items
              items={ready ? analysis.actions_requiring_approval : []}
              empty="제시된 승인 필요 조치 없음"
            />
          </div>
        </div>
        <div className="report-cell report-cell--wide">
          <strong>참조 매뉴얼·이력</strong>
          <div className="report-analysis-content">
            <Items
              items={
                ready
                  ? analysis.evidence?.map((item) => evidenceLabel(item))
                  : []
              }
              empty="연결된 근거 없음"
            />
          </div>
        </div>
      </div>
    </section>
  )
}
