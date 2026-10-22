# data

원본은 고치지 않는다. 가공한 결과물은 새 파일 이름으로 만들고 아래 표에 추가한다.

| 경로 | 내용 | 출처 |
|---|---|---|
| `telemetry/battery_tray_transfer_telemetry_v3_15cols.csv` | Telemetry v3 원본 60행(1초 간격). 전류·외함 온도는 전부 빈 값. SHA-256 `66f2ee2e…381a6` | 노션 1차 분담 최종 문서 |
| `rulebase/BTT-RULE_v2.0.pdf` | 룰베이스 최종 정의서 BTT-RULE v2.0 (코드 31개, 임계값, 사건 저장 계약) | 노션 1차 분담 최종 문서 |
| `manuals/BTT-MANUAL_v2.0.pdf` | 에러코드·대응 매뉴얼 BTT-MANUAL v2.0 | 노션 1차 분담 최종 문서 |
| `regulations/BTT-SOP-001.pdf` | 사내 규정·SOP BTT-SOP-001 (조문형, 승인 전 초안) | 노션 1차 분담 최종 문서 |
| `templates/maintenance_report_form_v1.2.pdf` | 정비 보고서 양식 CONV-MR-S-001 v1.2 | 노션 1차 분담 최종 문서 |

- PDF는 `manuals/`, `rulebase/`, `regulations/`에 종류별로 분류한다. 현재 임시 색인 스크립트는 `manuals/BTT-MANUAL_v2.0.pdf`를 사용한다. 문서가 바뀌면 버전이 드러나는 새 파일 이름으로 넣는다(인용 문자열에 버전이 들어가기 때문).
- 모든 수치는 시연용 합성·지정값이다. 실제 설비 진단 근거로 쓰지 않는다(정의서 1절).
- 큰 파일(수십 MB 이상)이나 개인정보는 커밋하지 않는다.
