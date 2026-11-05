import {
  Fragment,
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type ComponentPropsWithoutRef,
  type ChangeEvent,
  type KeyboardEvent,
  type FormEvent,
} from 'react'

type SensorEvidence = {
  field: string
  valid?: boolean
  value?: boolean | number | null
  unit?: string
  observed?: string
  threshold?: string
}
export type ReportIncident = {
  incident_id: string
  process_id?: string
  asset_id?: string
  first_detected_at?: string
  last_detected_at?: string
  codes?: string[]
  evidence?: SensorEvidence[]
}
export type ReportTelemetry = {
  record_id: string
  timestamp: string
  process_id: string
  asset_id: string
  [field: string]: string | number | boolean | null | undefined
}
export type Analysis = {
  incident_id: string
  status: string
  observed_facts?: string
  suspected_causes?: {
    cause: string
    basis: string
    evidence_ids?: string[]
  }[]
  recommended_checks?: string[]
  recommended_actions?: string[]
  actions_requiring_approval?: string[]
  evidence?: { citation: string; evidence_id?: string }[]
  limitations?: string
}
type Values = Record<string, string>
type Change = ChangeEvent<
  HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement
>

import {
  alarmDescriptions,
  measurementSummary,
  reportEquipmentLabel,
  formatReportMeasurement,
} from './reportPresentation'
import './ReportForm.css'
import ReportAnalysisSection from './ReportAnalysisSection'

const initialValues = {
  author: '',
  department: '',
  processImpact: '미확인',
  actualActions: '',
  actionStatus: '수행',
  replacedParts: '',
  actionBy: '',
  actionAt: '',
  causeCategory: '',
  confirmedCause: '',
  causeEvidence: '',
  aiAssessment: '판단 불가',
  trialResult: '미실시',
  trialDetails: '',
  downtimeStart: '',
  downtimeEnd: '',
  resolution: '미확인',
  followUp: '',
  followUpOwner: '',
  followUpDue: '',
  confirmedBy: '',
  confirmedAt: '',
}

function Section({
  number,
  title,
  children,
}: {
  number: string
  title: string
  children: ReactNode
}) {
  return (
    <section className="report-section">
      <h3 className="report-section-title">
        <span>{number}</span>
        {title}
      </h3>
      {children}
    </section>
  )
}

function ReadValue({
  label,
  children,
  wide = false,
}: {
  label: string
  children?: ReactNode
  wide?: boolean
}) {
  return (
    <div className={`report-read-value${wide ? ' report-wide' : ''}`}>
      <dt>{label}</dt>
      <dd>{children ?? '아직 연결되지 않았습니다.'}</dd>
    </div>
  )
}

function AutoTextarea({
  onChange,
  value,
  ...props
}: ComponentPropsWithoutRef<'textarea'>) {
  const ref = useRef<HTMLTextAreaElement>(null)

  function fit() {
    const element = ref.current
    if (!element) return
    element.style.height = 'auto'
    element.style.height = `${element.scrollHeight}px`
  }

  useEffect(() => {
    fit()
  }, [value])

  return (
    <textarea
      {...props}
      ref={ref}
      value={value}
      onChange={(event) => {
        fit()
        onChange?.(event)
      }}
    />
  )
}

function Field({
  label,
  name,
  value,
  onChange,
  type = 'text',
  options,
  wide = false,
  required = false,
  readOnly = false,
  bare = false,
  placeholder,
}: {
  label: string
  name: string
  value: string
  onChange: (event: Change) => void
  type?: string
  options?: string[]
  wide?: boolean
  required?: boolean
  readOnly?: boolean
  bare?: boolean
  placeholder?: string
}) {
  const props = {
    name,
    value,
    onChange,
    required,
    readOnly,
  }
  const classes = [
    wide && 'report-wide',
    bare && 'report-field--bare',
    bare && !value && 'is-empty',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <label
      className={classes || undefined}
      data-placeholder={bare ? placeholder : undefined}
    >
      <span className={bare ? 'report-sr-only' : undefined}>
        {label}
        {required && ' *'}
      </span>

      {options ? (
        <select {...props}>
          {options.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      ) : type === 'textarea' ? (
        <AutoTextarea {...props} placeholder={placeholder} rows={1} />
      ) : (
        <input {...props} placeholder={placeholder} type={type} />
      )}
    </label>
  )
}

function SubRows({ rows }: { rows: [string, ReactNode, boolean?][] }) {
  return (
    <div className="report-subtable">
      {rows.map(([label, field, required]) => (
        <Fragment key={label}>
          <span className="report-sub-label">
            {label}
            {required && ' *'}
          </span>
          <div>{field}</div>
        </Fragment>
      ))}
    </div>
  )
}

function Auto({ children }: { children?: ReactNode }) {
  return children || <span className="report-placeholder">자동 입력</span>
}

const PHOTO_TYPES = ['image/jpeg', 'image/png', 'image/webp']

function PhotoField({
  side,
  title,
  onEdit,
}: {
  side: string
  title: string
  onEdit: () => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [photoError, setPhotoError] = useState('')
  const imageRef = useRef<HTMLImageElement>(null)

  useEffect(() => {
    if (!file || !imageRef.current) return

    const url = URL.createObjectURL(file)
    imageRef.current.src = url

    return () => URL.revokeObjectURL(url)
  }, [file])

  // 읽기 상태(fieldset disabled)에서도 선택창이 열리도록 fieldset 밖에서 만든 input을 사용한다.
  function openPicker() {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = PHOTO_TYPES.join(',')
    input.addEventListener('change', () => {
      const selected = input.files?.[0] ?? null

      if (selected && !PHOTO_TYPES.includes(selected.type)) {
        setFile(null)
        setPhotoError('JPG, PNG, WebP 이미지를 선택하세요.')
      } else {
        setPhotoError('')
        if (selected) setFile(selected)
      }

      onEdit()
    })
    input.click()
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      openPicker()
    }
  }

  return (
    <div className="report-photo">
      <h4>{title}</h4>

      <div className="report-photo-body">
        <div
          className="report-photo-preview"
          role="button"
          tabIndex={0}
          aria-label={`${title} 사진 첨부`}
          onClick={openPicker}
          onKeyDown={handleKeyDown}
        >
          {file ? (
            <img ref={imageRef} alt={`${title} 미리보기`} />
          ) : (
            <p>
              <strong>{title} 사진 1장 첨부</strong>
              <br />
              비율 유지 / 원본은 연결 사건에 보관
            </p>
          )}
        </div>
        {photoError && (
          <p className="error" role="alert">
            {photoError}
          </p>
        )}

        <label className="report-photo-caption">
          <span>
            <strong>캡션</strong>
            {side === 'before'
              ? ' · 이상 부위 · 관측 상태'
              : ' · 조치 내용 · 복구 상태'}
          </span>
          <AutoTextarea name={`${side}_caption`} rows={1} onChange={onEdit} />
        </label>

        <div className="report-photo-meta">
          <label>
            촬영 시각
            <input
              type="datetime-local"
              name={`${side}_taken_at`}
              onChange={onEdit}
            />
          </label>

          <label>
            촬영 위치
            <input name={`${side}_location`} onChange={onEdit} />
          </label>
        </div>
      </div>
    </div>
  )
}

function formatTime(value: string | null | undefined) {
  if (!value) return ''

  const date = new Date(value)

  return Number.isNaN(date.getTime())
    ? '시각 확인 필요'
    : date.toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' })
}

export default function ReportForm({
  incident = null,
  analysis = null,
  analysisInput = null,
  telemetry = null,
  telemetryAnchor = null,
  telemetryNotes = [],
  reportId = '',
  assetName = '',
  savedValues = {},
  author = null,
  statusLabel = '초안',
  readOnly = false,
  busy = false,
  onSave,
  onSubmit,
  saveOnly = false,
  saveOnlyLabel = '저장 후 제출',
}: {
  incident?: ReportIncident | null
  analysis?: Analysis | null
  analysisInput?: ReportIncident | null
  telemetry?: ReportTelemetry | null
  telemetryAnchor?: string | null
  telemetryNotes?: string[]
  reportId?: string
  assetName?: string
  savedValues?: Values
  author?: { name: string; employee_no: string } | null
  statusLabel?: string
  readOnly?: boolean
  busy?: boolean
  onSave?: (values: Values) => void | Promise<void>
  onSubmit?: (values: Values) => void | Promise<void>
  saveOnly?: boolean
  saveOnlyLabel?: string
}) {
  const [values, setValues] = useState<Values>(() => ({
    ...initialValues,
    ...savedValues,
    author: author?.name ?? '',
    actionBy: author?.employee_no ?? '',
    confirmedBy: author?.name ?? '',
  }))
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  // 수정 버튼 없이 바로 입력할 수 있다. 읽기 전용이거나 저장 중일 때만 잠근다.
  const locked = readOnly || busy

  // 다른 사건의 분석 결과가 현재 보고서에 섞이지 않도록 확인한다.
  const linkedAnalysis =
    incident?.incident_id && analysis?.incident_id === incident.incident_id
      ? analysis
      : null

  function clearFeedback() {
    setMessage('')
    setError('')
  }

  function handleChange(event: Change) {
    const { name, value } = event.currentTarget

    setValues((previous) => ({
      ...previous,
      [name]: value,
    }))
    clearFeedback()
  }

  function getSensor(field: string) {
    if (
      !incident ||
      !telemetry ||
      telemetry?.process_id !== incident.process_id ||
      telemetry?.asset_id !== incident.asset_id
    )
      return null
    const value = telemetry[field]
    return typeof value === 'boolean' ||
      (typeof value === 'number' && Number.isFinite(value))
      ? value
      : null
  }

  const observedIncident = linkedAnalysis
    ? analysisInput?.incident_id === incident?.incident_id &&
      analysisInput?.process_id === incident?.process_id &&
      analysisInput?.asset_id === incident?.asset_id
      ? analysisInput
      : null
    : incident

  const sensors = [
    ['회전속도 r/min', 'rpm'],
    ['DC 입력 전류 A', 'dc_input_current_a'],
    ['DC 버스 전압 V', 'dc_bus_voltage_v'],
    ['모터 하우징 온도 °C', 'motor_housing_temp_c'],
    ['입구 감지', 'infeed_present'],
    ['출구 감지', 'outfeed_present'],
    ['구동측 진동 RMS g', 'de_vibration_rms_g'],
    ['구동측 첨도', 'de_kurtosis'],
    ['반구동측 진동 RMS g', 'nde_vibration_rms_g'],
    ['반구동측 첨도', 'nde_kurtosis'],
  ]

  const hasDowntime =
    Boolean(values.downtimeStart) && Boolean(values.downtimeEnd)

  const downtimeMinutes = hasDowntime
    ? (new Date(values.downtimeEnd).getTime() -
        new Date(values.downtimeStart).getTime()) /
      60_000
    : null

  async function handleCheck(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    clearFeedback()

    if (saveOnly) {
      await onSave?.(values)
      return
    }

    if (
      downtimeMinutes !== null &&
      (!Number.isFinite(downtimeMinutes) || downtimeMinutes < 0)
    ) {
      setError('운전 복귀 시각은 정지 시작 시각 이후여야 합니다.')
      return
    }

    if (onSubmit) {
      await onSubmit(values)
    } else {
      setMessage('입력 형식을 확인했습니다.')
    }
  }

  function renderField(name: string, label: string, extra = {}) {
    return (
      <Field
        name={name}
        label={label}
        value={values[name]}
        onChange={handleChange}
        {...extra}
      />
    )
  }

  return (
    <article className="report-sheet">
      <header className="report-heading">
        <p className="report-meta">
          <span>정비관리 | CONV-MR-S-001 | 양식 v1.2</span>
          <span>현장 사진(전·후) 포함 / 1쪽 양식</span>
        </p>
        <h2>컨베이어 설비 이상 정비 보고서</h2>
        <p>기본 보고서 발생 사실과 AI 제안 및 실제 조치 결과를 구분하여 작성</p>
      </header>

      <form onSubmit={handleCheck}>
        <fieldset disabled={locked} className="report-fields">
          <Section number="01" title="기본 정보">
            <div className="report-table report-table--basic">
              <div className="report-cell">
                <strong>보고서 번호</strong>
                <span>
                  <Auto>{reportId}</Auto>
                </span>
              </div>
              <div className="report-cell">
                <strong>연결 사건</strong>
                <span>
                  <Auto>{incident?.incident_id}</Auto>
                </span>
              </div>
              <div className="report-cell">
                <strong>공정 설비</strong>
                <span>
                  <Auto>
                    {[incident?.process_id, incident?.asset_id]
                      .filter(Boolean)
                      .join(' / ')}
                  </Auto>
                </span>
              </div>
              <div className="report-cell">
                <strong>설비명 모델</strong>
                <span>
                  <Auto>
                    {reportEquipmentLabel(incident?.asset_id, assetName)}
                  </Auto>
                </span>
              </div>
              <div className="report-cell">
                <strong>발생 시각</strong>
                <span>
                  <Auto>{formatTime(incident?.first_detected_at)}</Auto>
                </span>
              </div>
              <div className="report-cell">
                <strong>작성자 부서</strong>
                <div>
                  {renderField('department', '작성자 부서', {
                    bare: true,
                    placeholder: '입력',
                  })}
                </div>
              </div>
              <div className="report-cell">
                <strong>문서 상태</strong>
                <span>{statusLabel}</span>
              </div>
              <div className="report-cell">
                <strong>공정 영향</strong>
                <div>
                  {renderField('processImpact', '공정 영향', {
                    bare: true,
                    options: ['미확인', '정지', '감속', '영향 없음'],
                  })}
                </div>
              </div>
            </div>
          </Section>

          <Section number="02" title="발생 현상 및 주요 측정값">
            <div className="report-table report-table--observations">
              <div className="report-cell report-cell--wide">
                <strong>알람 코드</strong>
                <span>{incident?.codes?.join(', ') || '알람 미확인'}</span>
              </div>
              <div className="report-cell report-cell--wide">
                <strong>관측 현상</strong>
                <span style={{ whiteSpace: 'pre-line' }}>
                  {alarmDescriptions(incident, linkedAnalysis).join('\n') ||
                    '알람 미확인'}
                  {observedIncident?.evidence?.length
                    ? `\n${observedIncident.evidence.map(measurementSummary).join('\n')}`
                    : ''}
                </span>
              </div>
              <div className="report-cell">
                <strong>최초 감지</strong>
                <span>
                  {formatTime(incident?.first_detected_at) || '시각 미확인'}
                </span>
              </div>
              <div className="report-cell">
                <strong>마지막 감지</strong>
                <span>
                  {formatTime(incident?.last_detected_at) || '시각 미확인'}
                </span>
              </div>
              <div className="report-cell report-cell--wide">
                <strong>측정값 표본 시각</strong>
                <span>
                  {formatTime(telemetry?.timestamp) || '표본 없음'}
                  {telemetryAnchor &&
                    ` · 조회 기준: ${formatTime(telemetryAnchor)}`}
                </span>
              </div>
            </div>
            <div className="report-sensors">
              {sensors.map(([label, field]) => (
                <div key={field}>
                  <strong>{label}</strong>
                  <span>
                    {formatReportMeasurement(field, getSensor(field))}
                  </span>
                </div>
              ))}
            </div>
            {telemetryNotes.map((note) => (
              <p className="report-note" key={note}>
                {note}
              </p>
            ))}
          </Section>

          <ReportAnalysisSection
            analysis={linkedAnalysis}
            incident={incident}
          />

          <Section number="04" title="실제 점검 및 조치 결과">
            <div className="report-table report-table--rows">
              <strong className="report-th">실제 조치 및 부품</strong>
              <div className="report-td">
                <SubRows
                  rows={[
                    [
                      '실제 조치 여부',
                      renderField('actionStatus', '실제 조치 여부', {
                        bare: true,
                        options: ['수행', '미수행'],
                      }),
                    ],
                    [
                      '수행 내용 · 미수행 사유',
                      renderField(
                        'actualActions',
                        '실제 수행 내용 또는 미수행 사유',
                        {
                          bare: true,
                          type: 'textarea',
                          required: true,
                          placeholder: '수행 내용 (미수행이면 사유)',
                        },
                      ),
                      true,
                    ],
                    [
                      '교체 부품',
                      renderField('replacedParts', '교체 부품', {
                        bare: true,
                        type: 'textarea',
                        placeholder: '없으면 ‘없음’',
                      }),
                    ],
                    [
                      '조치 기록자 사번',
                      renderField('actionBy', '조치 기록자 사번', {
                        bare: true,
                        readOnly: true,
                      }),
                    ],
                    [
                      '조치 시각',
                      renderField('actionAt', '조치 시각', {
                        bare: true,
                        type: 'datetime-local',
                        placeholder: '입력',
                        required: values.actionStatus === '수행',
                      }),
                      values.actionStatus === '수행',
                    ],
                  ]}
                />
              </div>
              <strong className="report-th">확인 원인 및 근거</strong>
              <div className="report-td">
                <SubRows
                  rows={[
                    [
                      '확인 원인',
                      renderField('confirmedCause', '확인 원인', {
                        bare: true,
                        type: 'textarea',
                        required: true,
                        placeholder: '미확인이면 그 사실, 확인했다면 원인',
                      }),
                      true,
                    ],
                    [
                      '원인 확인 근거',
                      renderField('causeEvidence', '원인 확인 근거', {
                        bare: true,
                        type: 'textarea',
                        placeholder: '확인했다면 원인과 확인 근거',
                      }),
                    ],
                    [
                      '원인 분류',
                      renderField('causeCategory', '원인 분류', {
                        bare: true,
                        placeholder: '입력',
                      }),
                    ],
                    [
                      'AI 제안과 실제 결과 비교',
                      renderField('aiAssessment', 'AI 제안과 실제 결과 비교', {
                        bare: true,
                        options: ['판단 불가', '일치', '부분 일치', '불일치'],
                      }),
                    ],
                  ]}
                />
              </div>
            </div>
          </Section>

          <Section number="05" title="복구 확인 및 처리 결과">
            <div className="report-table report-table--recovery">
              <strong className="report-th">복구 시험 및 결과</strong>
              <div className="report-td report-td--span">
                <SubRows
                  rows={[
                    [
                      '복구 시험 결과',
                      renderField('trialResult', '복구 시험 결과', {
                        bare: true,
                        options: ['미실시', '정상', '부적합'],
                      }),
                    ],
                    [
                      '시험 내용 · 미실시 사유',
                      renderField(
                        'trialDetails',
                        '시험 내용·결과 또는 미실시 사유',
                        {
                          bare: true,
                          type: 'textarea',
                          required: true,
                          placeholder: '적합 / 부적합 / 미실시 (미실시면 사유)',
                        },
                      ),
                      true,
                    ],
                  ]}
                />
              </div>
              <strong className="report-th">정지 시작</strong>
              <div className="report-td">
                {renderField('downtimeStart', '정지 시작', {
                  type: 'datetime-local',
                  bare: true,
                  placeholder: '입력',
                })}
              </div>
              <strong className="report-th">운전 복귀</strong>
              <div className="report-td">
                {renderField('downtimeEnd', '운전 복귀', {
                  type: 'datetime-local',
                  bare: true,
                  placeholder: '입력',
                })}
              </div>
              <strong className="report-th">총 정지 분</strong>
              <div className="report-td">
                <span>
                  {downtimeMinutes === null
                    ? '구간 확인 후 계산'
                    : !Number.isFinite(downtimeMinutes) || downtimeMinutes < 0
                      ? '정지 구간을 확인하세요.'
                      : `${Number(downtimeMinutes.toFixed(2))}분`}
                </span>
              </div>
              <strong className="report-th">처리 결과</strong>
              <div className="report-td">
                {renderField('resolution', '처리 결과', {
                  options: ['미확인', '해결', '미해결', '보류'],
                  bare: true,
                })}
              </div>
              <strong className="report-th">후속 조치 및 담당</strong>
              <div className="report-td report-td--span">
                <SubRows
                  rows={[
                    [
                      '후속 조치',
                      renderField('followUp', '후속 조치', {
                        bare: true,
                        type: 'textarea',
                        placeholder:
                          '미해결 사항 · 담당자 · 기한 (해당 없으면 ‘없음’)',
                      }),
                    ],
                    [
                      '후속 조치 담당자',
                      renderField('followUpOwner', '후속 조치 담당자', {
                        bare: true,
                        placeholder: '입력',
                      }),
                    ],
                    [
                      '후속 조치 기한',
                      renderField('followUpDue', '후속 조치 기한', {
                        bare: true,
                        type: 'date',
                        placeholder: '입력',
                      }),
                    ],
                  ]}
                />
              </div>
              <strong className="report-th">작성 확인</strong>
              <div className="report-td">
                {renderField('confirmedBy', '작성 확인 성명', {
                  readOnly: true,
                  bare: true,
                })}
              </div>
              <strong className="report-th">검토 확정</strong>
              <div className="report-td">
                <span>제출·결재 이력으로 확인</span>
              </div>
            </div>
          </Section>

          <Section number="06" title="현장 사진 (조치 전·후)">
            <p className="report-note">
              사진은 미리보기용입니다. 현재 임시 저장·제출에 사진 파일은
              포함되지 않습니다.
            </p>
            <div className="report-photo-grid">
              <PhotoField
                side="before"
                title="조치 전"
                onEdit={clearFeedback}
              />
              <PhotoField side="after" title="조치 후" onEdit={clearFeedback} />
            </div>
          </Section>

          <p className="report-note">
            AI 권고를 실제 수행으로 기입하지 않습니다. 정지시간은 알람
            지속시간과 다르며 상세 센서 로그와 전·후 사진 원본은 연결 사건에
            보관합니다.
          </p>

          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          {message && (
            <p className="report-feedback" role="status">
              {message}
            </p>
          )}
        </fieldset>

        <footer className="report-footer">
          <span>
            {saveOnly
              ? '저장 후 완료는 초안으로 보관되며, 검토나 제출은 진행하지 않습니다.'
              : '* 제출 시 필수 입력. 임시 저장은 빈 칸을 허용합니다.'}{' '}
            입력 시각은 브라우저의 현지 시간 기준입니다.
          </span>
          {!readOnly && onSave && !saveOnly && (
            <button
              type="button"
              disabled={busy}
              onClick={() => void onSave(values)}
            >
              임시 저장
            </button>
          )}
          {!readOnly && saveOnly && (
            <>
              <button
                type="button"
                className="report-check-button"
                disabled={busy}
                onClick={() => void onSave?.(values)}
              >
                {saveOnlyLabel}
              </button>
            </>
          )}
          {!readOnly && !saveOnly && (
            <button
              type="submit"
              className="report-check-button"
              disabled={busy}
            >
              {onSubmit ? '저장 후 제출' : '작성 내용 확인'}
            </button>
          )}
        </footer>
      </form>

      <div className="report-paper-footer">
        <span>AI 초안과 실제 확인 결과를 구분하여 기록</span>
        <span>CONV-MR-S-001 | v1.2 | 1 / 1</span>
      </div>
    </article>
  )
}
