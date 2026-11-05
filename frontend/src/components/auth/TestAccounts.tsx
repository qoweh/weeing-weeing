// 시연 기간 팀원 테스트 계정(사람마다 직책별 5개). 비밀번호는 팀 공통 값이라 여기 두지 않는다.
// 시연이 끝나면 지운다: 이 파일, LoginPage의 <TestAccounts /> 줄과 import, login.scss의 "테스트 계정" 블록.
type TestAccount = { role: string; employeeNo: string }

const testPeople: { name: string; accounts: TestAccount[] }[] = [
  {
    name: 'qoweh',
    accounts: [
      { role: '관리자 (관제)', employeeNo: 'ADMIN1' },
      { role: '관제 담당자', employeeNo: 'C1101' },
      { role: '보전 팀장', employeeNo: 'L2101' },
      { role: '현장 책임자', employeeNo: 'M3101' },
      { role: '현장 점검자', employeeNo: 'I4101' },
    ],
  },
  {
    name: 'Laplace888',
    accounts: [
      { role: '관리자 (관제)', employeeNo: 'ADMIN2' },
      { role: '관제 담당자', employeeNo: 'C1201' },
      { role: '보전 팀장', employeeNo: 'L2201' },
      { role: '현장 책임자', employeeNo: 'M3201' },
      { role: '현장 점검자', employeeNo: 'I4201' },
    ],
  },
  {
    name: 'BoyeongIm',
    accounts: [
      { role: '관리자 (관제)', employeeNo: 'ADMIN3' },
      { role: '관제 담당자', employeeNo: 'C1301' },
      { role: '보전 팀장', employeeNo: 'L2301' },
      { role: '현장 책임자', employeeNo: 'M3301' },
      { role: '현장 점검자', employeeNo: 'I4301' },
    ],
  },
  {
    name: 'Gilssom',
    accounts: [
      { role: '관리자 (관제)', employeeNo: 'ADMIN4' },
      { role: '관제 담당자', employeeNo: 'C1401' },
      { role: '보전 팀장', employeeNo: 'L2401' },
      { role: '현장 책임자', employeeNo: 'M3401' },
      { role: '현장 점검자', employeeNo: 'I4401' },
    ],
  },
  {
    name: 'GyuHyunA (ghahn97)',
    accounts: [
      { role: '관리자 (관제)', employeeNo: 'ADMIN5' },
      { role: '관제 담당자', employeeNo: 'C1501' },
      { role: '보전 팀장', employeeNo: 'L2501' },
      { role: '현장 책임자', employeeNo: 'M3501' },
      { role: '현장 점검자', employeeNo: 'I4501' },
    ],
  },
  {
    name: 'ehddls1590-hub',
    accounts: [
      { role: '관리자 (관제)', employeeNo: 'ADMIN6' },
      { role: '관제 담당자', employeeNo: 'C1601' },
      { role: '보전 팀장', employeeNo: 'L2601' },
      { role: '현장 책임자', employeeNo: 'M3601' },
      { role: '현장 점검자', employeeNo: 'I4601' },
    ],
  },
]

export default function TestAccounts() {
  return (
    <section className="test-accounts" aria-labelledby="test-accounts-title">
      <h2 id="test-accounts-title">팀원 테스트 계정</h2>
      <p>
        비밀번호는 모든 계정이 팀 공통 비밀번호입니다(김민우에게 받기). 본인
        계정만 쓰세요. 사용량이 계정 이름으로 기록됩니다. 관리자도 다른 직책
        업무는 못 하므로, 보고서는 점검자 제출 → 보전 팀장 검토 → 관제 승인
        순으로 계정을 바꿔 가며 확인합니다.
      </p>
      <div className="test-accounts__grid">
        {testPeople.map((person) => (
          <table key={person.name} className="test-accounts__person">
            <caption>{person.name}</caption>
            <thead>
              <tr>
                <th scope="col">직책</th>
                <th scope="col">사번</th>
              </tr>
            </thead>
            <tbody>
              {person.accounts.map((account) => (
                <tr key={account.employeeNo}>
                  <th scope="row">{account.role}</th>
                  <td>
                    <code>{account.employeeNo}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ))}
      </div>
    </section>
  )
}
