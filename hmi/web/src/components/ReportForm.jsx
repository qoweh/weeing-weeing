import { useEffect, useRef, useState } from "react";

import { alarmDescriptions, measurementSummary } from "./reportPresentation";
import "./ReportForm.css";

const initialValues = {
  author: "",
  department: "",
  processImpact: "미확인",
  actualActions: "",
  actionStatus: "수행",
  replacedParts: "",
  actionBy: "",
  actionAt: "",
  causeCategory: "",
  confirmedCause: "",
  causeEvidence: "",
  aiAssessment: "판단 불가",
  trialResult: "미실시",
  trialDetails: "",
  downtimeStart: "",
  downtimeEnd: "",
  resolution: "미확인",
  followUp: "",
  followUpOwner: "",
  followUpDue: "",
  confirmedBy: "",
  confirmedAt: "",
};

function Section({ number, title, children }) {
  return (
    <section className="report-section">
      <h3 className="report-section-title">
        <span>{number}</span>
        {title}
      </h3>
      {children}
    </section>
  );
}

function ReadValue({ label, children, wide = false }) {
  return (
    <div className={`report-read-value${wide ? " report-wide" : ""}`}>
      <dt>{label}</dt>
      <dd>{children ?? "아직 연결되지 않았습니다."}</dd>
    </div>
  );
}

function Field({
  label,
  name,
  value,
  onChange,
  type = "text",
  options,
  wide = false,
  required = false,
  readOnly = false,
}) {
  const props = {
    name,
    value,
    onChange,
    required,
    readOnly,
  };

  return (
    <label className={wide ? "report-wide" : undefined}>
      <span>
        {label}
        {required && " *"}
      </span>

      {options ? (
        <select {...props}>
          {options.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      ) : type === "textarea" ? (
        <textarea {...props} rows={3} />
      ) : (
        <input {...props} type={type} />
      )}
    </label>
  );
}

function PhotoField({ side, title, onEdit }) {
  const [file, setFile] = useState(null);
  const imageRef = useRef(null);

  useEffect(() => {
    if (!file || !imageRef.current) return;

    const url = URL.createObjectURL(file);
    imageRef.current.src = url;

    return () => URL.revokeObjectURL(url);
  }, [file]);

  function handleFileChange(event) {
    const input = event.currentTarget;
    const selected = input.files?.[0] ?? null;
    const allowed = ["image/jpeg", "image/png", "image/webp"];

    if (selected && !allowed.includes(selected.type)) {
      input.setCustomValidity("JPG, PNG, WebP 이미지를 선택하세요.");
      input.reportValidity();
      input.value = "";
      setFile(null);
    } else {
      input.setCustomValidity("");
      setFile(selected);
    }

    onEdit();
  }

  return (
    <div className="report-photo">
      <h4>{title}</h4>

      <div className="report-photo-body">
        <div className="report-photo-preview">
          {file ? (
            <img ref={imageRef} alt={`${title} 미리보기`} />
          ) : (
            <p>{title} 사진 1장을 선택하세요.</p>
          )}
        </div>

        <label>
          사진 선택
          <input
            type="file"
            name={`${side}_photo`}
            accept="image/jpeg,image/png,image/webp"
            onChange={handleFileChange}
          />
        </label>

        <label>
          캡션
          <textarea
            name={`${side}_caption`}
            rows={2}
            placeholder={
              side === "before"
                ? "이상 부위와 관측 상태"
                : "실제 조치 내용과 복구 상태"
            }
            onChange={onEdit}
          />
        </label>

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
          <input
            name={`${side}_location`}
            onChange={onEdit}
          />
        </label>
      </div>
    </div>
  );
}

function formatTime(value) {
  if (!value) return "아직 연결되지 않았습니다.";

  const date = new Date(value);

  return Number.isNaN(date.getTime())
    ? "시각 확인 필요"
    : date.toLocaleString("ko-KR", { timeZone: "Asia/Seoul" });
}

export default function ReportForm({
  incident = null,
  analysis = null,
  telemetry = null,
  reportId = "",
  assetName = "",
  savedValues = {},
  author = null,
  statusLabel = "초안",
  readOnly = false,
  busy = false,
  onSave,
  onSubmit,
}) {
  const [values, setValues] = useState(() => ({
    ...initialValues, ...savedValues,
    author: author?.name ?? "",
    actionBy: author?.employee_no ?? "",
    confirmedBy: author?.name ?? "",
  }));
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  // 다른 사건의 분석 결과가 현재 보고서에 섞이지 않도록 확인한다.
  const linkedAnalysis =
    incident?.incident_id &&
    analysis?.incident_id === incident.incident_id
      ? analysis
      : null;

  const analysisReady = linkedAnalysis?.status === "OK";

  const analysisMessage = !linkedAnalysis
    ? "AI 초안이 아직 연결되지 않았습니다."
    : linkedAnalysis.status === "INSUFFICIENT_EVIDENCE"
      ? "근거가 부족해 AI 초안 작성을 중단했습니다."
      : "AI 분석에 실패했습니다. 담당자 확인이 필요합니다.";

  function clearFeedback() {
    setMessage("");
    setError("");
  }

  function handleChange(event) {
    const { name, value } = event.currentTarget;

    setValues((previous) => ({
      ...previous,
      [name]: value,
    }));
    clearFeedback();
  }

  const observations = alarmDescriptions(incident, linkedAnalysis);

  const hasDowntime =
    Boolean(values.downtimeStart) && Boolean(values.downtimeEnd);

  const downtimeMinutes = hasDowntime
    ? (
        new Date(values.downtimeEnd).getTime() -
        new Date(values.downtimeStart).getTime()
      ) / 60_000
    : null;

  async function handleCheck(event) {
    event.preventDefault();
    clearFeedback();

    if (
      downtimeMinutes !== null &&
      (!Number.isFinite(downtimeMinutes) || downtimeMinutes < 0)
    ) {
      setError("운전 복귀 시각은 정지 시작 시각 이후여야 합니다.");
      return;
    }

    if (onSubmit) {
      await onSubmit(values);
    } else {
      setMessage("입력 형식을 확인했습니다.");
    }
  }

  function renderField(name, label, extra = {}) {
    return (
      <Field
        name={name}
        label={label}
        value={values[name]}
        onChange={handleChange}
        {...extra}
      />
    );
  }

  return (
    <article className="report-sheet">
      <header className="report-heading">
        <p className="report-meta">
          정비관리 | CONV-MR-S-001 | 양식 v1.2
        </p>
        <h2>컨베이어 설비 이상 정비 보고서</h2>
        <p>발생 사실과 AI 제안 및 실제 조치 결과를 구분하여 작성</p>
      </header>

      <form onSubmit={handleCheck}>
        <fieldset disabled={readOnly || busy} className="report-fields">
        <Section number="01" title="기본 정보">
          <dl className="report-read-grid">
            <ReadValue label="보고서 번호">
              {reportId || "저장 시 자동 발급"}
            </ReadValue>
            <ReadValue label="연결 사건">
              {incident?.incident_id}
            </ReadValue>
            <ReadValue label="공정 / 설비">
              {incident
                ? `${incident.process_id} / ${incident.asset_id}`
                : null}
            </ReadValue>
            <ReadValue label="설비명 / 모델">
              {assetName || null}
            </ReadValue>
            <ReadValue label="발생 시각">
              {formatTime(incident?.first_detected_at)}
            </ReadValue>
            <ReadValue label="문서 상태">{statusLabel}</ReadValue>
          </dl>

          <div className="report-input-grid">
            {renderField("author", "작성자", { readOnly: true })}
            {renderField("department", "부서")}
            {renderField("processImpact", "공정 영향", {
              options: ["미확인", "정지", "감속", "영향 없음"],
              wide: true,
            })}
          </div>
        </Section>

        <Section number="02" title="발생 현상 및 주요 측정값">
          <dl className="report-read-grid">
            <ReadValue label="알람 코드" wide>
              {incident?.codes?.join(", ") || "연결 사건 대기"}
            </ReadValue>
            <ReadValue label="관측 현상" wide>
              {observations.length ? (
                <>
                  {observations.join("\n")}
                  {"\n"}
                  {incident.evidence?.length
                    ? incident.evidence.map(measurementSummary).join("\n")
                    : "판정 측정값 연결 대기"}
                </>
              ) : "관측 사실 연결 대기"}
            </ReadValue>
            <ReadValue label="최초 감지">
              {formatTime(incident?.first_detected_at)}
            </ReadValue>
            <ReadValue label="마지막 감지">
              {formatTime(incident?.last_detected_at)}
            </ReadValue>
            {telemetry && <>
              <ReadValue label="센서 표본 시각" wide>{formatTime(telemetry.timestamp)}</ReadValue>
              {[["입구 센서", "infeed_present", ""], ["출구 센서", "outfeed_present", ""], ["회전 속도", "rpm", "rpm"], ["DC 입력 전류", "dc_input_current_a", "A"], ["DC 버스 전압", "dc_bus_voltage_v", "V"], ["모터 외함 온도", "motor_housing_temp_c", "℃"], ["구동측 진동 RMS", "de_vibration_rms_g", "g"], ["구동측 첨도", "de_kurtosis", ""], ["반구동측 진동 RMS", "nde_vibration_rms_g", "g"], ["반구동측 첨도", "nde_kurtosis", ""]].map(([label, field, unit]) => <ReadValue key={field} label={label}>{telemetry[field] == null ? "측정값 없음" : typeof telemetry[field] === "boolean" ? (telemetry[field] ? "감지" : "감지 안 됨") : `${telemetry[field]} ${unit}`}</ReadValue>)}
            </>}
          </dl>
        </Section>

        <Section number="03" title="AI 분석 및 대응 권고">
          {analysisReady ? (
            <dl className="report-read-grid">
              <ReadValue label="추정 원인 및 근거" wide>
                {linkedAnalysis.suspected_causes.length ? (
                  <ul>
                    {linkedAnalysis.suspected_causes.map((item, index) => (
                      <li key={index}>
                        <strong>{item.cause}</strong>
                        <br />
                        설비: {incident.process_id} / {incident.asset_id}
                        <br />
                        코드: {incident.codes.join(", ")}
                        <br />
                        근거 ID: {item.evidence_ids.join(", ")}
                      </li>
                    ))}
                  </ul>
                ) : (
                  "제시된 원인 후보 없음"
                )}
              </ReadValue>

              <ReadValue label="권고 점검 절차" wide>
                {linkedAnalysis.recommended_checks.length ? (
                  <ol>
                    {linkedAnalysis.recommended_checks.map((text, index) => (
                      <li key={index}>{text}</li>
                    ))}
                  </ol>
                ) : (
                  "제시된 점검 절차 없음"
                )}
              </ReadValue>

              <ReadValue label="권고 조치" wide>
                {linkedAnalysis.recommended_actions.length ? (
                  <ul>
                    {linkedAnalysis.recommended_actions.map((text, index) => (
                      <li key={index}>{text}</li>
                    ))}
                  </ul>
                ) : (
                  "제시된 권고 조치 없음"
                )}
              </ReadValue>

              <ReadValue label="승인이 필요한 조치" wide>
                {linkedAnalysis.actions_requiring_approval.length ? (
                  <ul>
                    {linkedAnalysis.actions_requiring_approval.map(
                      (text, index) => <li key={index}>{text}</li>,
                    )}
                  </ul>
                ) : (
                  "별도 제시 없음"
                )}
              </ReadValue>

              <ReadValue label="참조 매뉴얼·이력" wide>
                <ul>
                  {linkedAnalysis.evidence.map((item) => (
                    <li key={item.evidence_id}>
                      {item.citation} · 근거 ID: {item.evidence_id}
                    </li>
                  ))}
                </ul>
              </ReadValue>
            </dl>
          ) : (
            <div className="report-empty">
              <p>{analysisMessage}</p>
              {linkedAnalysis?.additional_checks?.length > 0 && (
                <ul>
                  {linkedAnalysis.additional_checks.map((text, index) => (
                    <li key={index}>{text}</li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {linkedAnalysis?.limitations && (
            <p className="report-note">{linkedAnalysis.limitations}</p>
          )}
        </Section>

        <Section number="04" title="실제 점검 및 조치 결과">
          <div className="report-input-grid">
            {renderField("actionStatus", "실제 조치 여부", { options: ["수행", "미수행"] })}
            {renderField("actualActions", "실제 수행 내용 또는 미수행 사유", {
              type: "textarea",
              wide: true,
              required: true,
            })}
            {renderField("replacedParts", "교체 부품 — 없으면 ‘없음’", {
              type: "textarea",
              wide: true,
            })}
            {renderField("actionBy", "조치 기록자 사번", { readOnly: true })}
            {renderField("actionAt", "조치 시각", {
              type: "datetime-local",
              required: values.actionStatus === "수행",
            })}
            {renderField("confirmedCause", "확인 원인 — 미확인이면 ‘미확인’", {
              type: "textarea",
              wide: true,
              required: true,
            })}
            {renderField("aiAssessment", "AI 제안과 실제 결과 비교", {
              options: ["판단 불가", "일치", "부분 일치", "불일치"],
            })}
          </div>
        </Section>

        <Section number="05" title="복구 확인 및 처리 결과">
          <div className="report-input-grid">
            {renderField("trialResult", "복구 시험 결과", {
              options: ["미실시", "정상", "부적합"],
            })}
            {renderField("resolution", "처리 결과", {
              options: ["미확인", "해결", "미해결", "보류"],
            })}
            {renderField("trialDetails", "시험 내용·결과 또는 미실시 사유", {
              type: "textarea",
              wide: true,
              required: true,
            })}
            {renderField("downtimeStart", "정지 시작", {
              type: "datetime-local",
            })}
            {renderField("downtimeEnd", "운전 복귀", {
              type: "datetime-local",
            })}
          </div>

          <dl className="report-read-grid">
            <ReadValue label="총 정지 시간" wide>
              {downtimeMinutes === null
                ? "정지 시작과 운전 복귀를 입력하면 계산합니다."
                : !Number.isFinite(downtimeMinutes) || downtimeMinutes < 0
                  ? "정지 구간을 확인하세요."
                  : `${Number(downtimeMinutes.toFixed(2))}분`}
            </ReadValue>
          </dl>

          <div className="report-input-grid">
            {renderField("confirmedBy", "작성 확인 성명", {
              readOnly: true,
            })}
          </div>

          <dl className="report-read-grid">
            <ReadValue label="검토 확정" wide>
              제출·결재 이력의 사용자와 시각으로 확인합니다.
            </ReadValue>
          </dl>
        </Section>

        <Section number="06" title="현장 사진 (조치 전·후)">
          <p className="report-note">사진은 미리보기용입니다. 현재 임시 저장·제출에 사진 파일은 포함되지 않습니다.</p>
          <div className="report-photo-grid">
            <PhotoField
              side="before"
              title="조치 전"
              onEdit={clearFeedback}
            />
            <PhotoField
              side="after"
              title="조치 후"
              onEdit={clearFeedback}
            />
          </div>
        </Section>

        <p className="report-note">
          AI 권고를 실제 수행으로 기입하지 않습니다.
          정지시간은 알람 지속시간과 다릅니다.
          입력 시각은 브라우저의 현지 시간 기준입니다.
        </p>

        {error && <p className="error" role="alert">{error}</p>}
        {message && <p className="report-feedback" role="status">{message}</p>}

        <footer className="report-footer">
          <span>* 제출 시 필수 입력. 임시 저장은 사건 선택이 필요하며 나머지 항목은 비워둘 수 있습니다.</span>
          {!readOnly && onSave && <button type="button" onClick={() => void onSave(values)}>임시 저장</button>}
          {!readOnly && <button type="submit" className="report-check-button">{onSubmit ? "저장 후 제출" : "작성 내용 확인"}</button>}
        </footer>
        </fieldset>
      </form>
    </article>
  );
}
