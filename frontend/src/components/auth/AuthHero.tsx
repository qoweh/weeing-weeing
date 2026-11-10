const features: [string, string][] = [
  ["사건 현황", "진행 중인 사건과 이력을 위험도 순으로 확인"],
  ["문서 검색", "매뉴얼·규정·룰베이스를 근거로 설비 정보 탐색"],
  ["정비 보고서", "사건별 보고서 초안 작성과 결재 진행"],
];

export function AuthBrand({ name = "위잉위잉" }: { name?: string }) {
  return (
    <div className="login-brand">
      <span className="login-brand__mark">
        <img src="/assets/IMAGE/weeing-logo.png" alt="" />
      </span>
      <span>
        {name}
        <small>Equipment AI</small>
      </span>
    </div>
  );
}

export default function AuthHero() {
  return (
    <>
      <AuthBrand />
      <section className="login-hero" aria-label="서비스 소개">
        <h2>
          설비 이상 상황을
          <br />
          근거와 함께 확인합니다
        </h2>
        <p>
          이상 사건, 정비 문서, 보고서를 한 곳에서 확인하고
          <br />
          AI가 제안한 내용은 담당자가 검토합니다.
        </p>
        <ol>
          {features.map(([title, text], index) => (
            <li key={title}>
              <span aria-hidden="true">{index + 1}</span>
              <strong>{title}</strong>
              <small>{text}</small>
            </li>
          ))}
        </ol>
      </section>
    </>
  );
}
