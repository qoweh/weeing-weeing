# RAG E2E 검증 결과

## 검색 비교

| 백엔드 | 방식 | hit@1 | hit@5 | MRR |
|---|---|---|---|---|
| qdrant | dense | 21/30 | 29/30 | 0.808 |
| qdrant | hybrid | 20/30 | 30/30 | 0.787 |
| qdrant | reranked | 24/30 | 30/30 | 0.878 |
| chroma | dense | 21/30 | 29/30 | 0.808 |
| chroma | hybrid | 20/30 | 30/30 | 0.792 |
| chroma | reranked | 24/30 | 30/30 | 0.878 |

## 근거 없음 질의

순위 지표는 정답이 있는 질의만 집계한다. 거절은 실제 빈 결과일 때만 성공이다.
| 백엔드 | 방식 | 거절 / 근거 없음 질의 | 오반환 |
|---|---|---|---|
| qdrant | dense | 0/6 | 6 |
| qdrant | hybrid | 0/6 | 6 |
| qdrant | reranked | 5/6 | 1 |
| chroma | dense | 0/6 | 6 |
| chroma | hybrid | 0/6 | 6 |
| chroma | reranked | 5/6 | 1 |

## 반환 1위 관련도 분포

필터를 끈 실행으로 기준값을 검토한다. 미측정(None)은 0으로 대체하지 않는다.
| 백엔드 | 질의 종류 | 측정 수 | 최소 | 평균 | 최대 |
|---|---|---|---|---|---|
| qdrant | 정답 있음 | 30 | 0.0905 | 0.7623 | 0.9938 |
| qdrant | 근거 없음 | 1 | 0.3736 | 0.3736 | 0.3736 |
| chroma | 정답 있음 | 30 | 0.0905 | 0.7623 | 0.9938 |
| chroma | 근거 없음 | 1 | 0.3736 | 0.3736 | 0.3736 |

## 색인·갱신

| 백엔드 | 색인(초) | 문서별 청크 수 | 실패 | 멱등(재실행 unchanged) | 갱신 |
|---|---|---|---|---|---|
| qdrant | 127.7 | BTT-MANUAL 29, BTT-RULE 21, BTT-SOP-001 37 | - | 통과 | 통과 |
| chroma | 2.1 | BTT-MANUAL 29, BTT-RULE 21, BTT-SOP-001 37 | - | 통과 | 통과 |

- qdrant 갱신: BTT-MANUAL 2.0 → 2.0-e2e: 옛 청크 0, 새 청크 29
- chroma 갱신: BTT-MANUAL 2.0 → 2.0-e2e: 옛 청크 0, 새 청크 29

## #6이 채울 메타데이터가 빠진 청크 (qdrant, 전체 87)

- `section`: 3
- `page`: 0
- `codes`: 55
- `citation`: 0

## 질의별 상위 5개 (qdrant)

- **q01** dense 정답 1위
  1. `BTT-MANUAL:2.0:0005` relevance=미측정 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP03 '
  2. `BTT-RULE:2.0:0001` relevance=미측정 '문맥: BTT-RULE > 01 적용 범위와 판정 원칙\n\n01 적용 범위'
  3. `BTT-RULE:2.0:0017` relevance=미측정 '문맥: BTT-RULE > 10 구현·인수시험·변경 관리\n\n10 구현·인'
  4. `BTT-SOP-001:1.1:0004` relevance=미측정 '문맥: BTT-SOP-001 > 제1장 총칙\n\n제4조(센서 관측의 한계)'
  5. `BTT-RULE:2.0:0009` relevance=미측정 '문맥: BTT-RULE > 06 광전센서 이벤트와 다중 트레이 추적\n\n0'
- **q01** hybrid 정답 3위
  1. `BTT-RULE:2.0:0001` relevance=미측정 '문맥: BTT-RULE > 01 적용 범위와 판정 원칙\n\n01 적용 범위'
  2. `BTT-SOP-001:1.1:0004` relevance=미측정 '문맥: BTT-SOP-001 > 제1장 총칙\n\n제4조(센서 관측의 한계)'
  3. `BTT-MANUAL:2.0:0005` relevance=미측정 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP03 '
  4. `BTT-RULE:2.0:0009` relevance=미측정 '문맥: BTT-RULE > 06 광전센서 이벤트와 다중 트레이 추적\n\n0'
  5. `BTT-RULE:2.0:0017` relevance=미측정 '문맥: BTT-RULE > 10 구현·인수시험·변경 관리\n\n10 구현·인'
- **q01** reranked 정답 1위
  1. `BTT-MANUAL:2.0:0005` relevance=0.7529 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP03 '
  2. `BTT-RULE:2.0:0001` relevance=0.2091 '문맥: BTT-RULE > 01 적용 범위와 판정 원칙\n\n01 적용 범위'
  3. `BTT-RULE:2.0:0009` relevance=0.1245 '문맥: BTT-RULE > 06 광전센서 이벤트와 다중 트레이 추적\n\n0'
  4. `BTT-MANUAL:2.0:0003` relevance=0.0969 '문맥: BTT-MANUAL > 02 이송·광전 코드 빠른 조회\n\n02 이'
  5. `BTT-MANUAL:2.0:0002` relevance=0.0743 '문맥: BTT-MANUAL > 02 이송·광전 코드 빠른 조회\n\n02 이'
- **q02** dense 정답 1위
  1. `BTT-MANUAL:2.0:0004` relevance=미측정 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP01 '
  2. `BTT-RULE:2.0:0009` relevance=미측정 '문맥: BTT-RULE > 06 광전센서 이벤트와 다중 트레이 추적\n\n0'
  3. `BTT-RULE:2.0:0010` relevance=미측정 '문맥: BTT-RULE > 06 광전센서 이벤트와 다중 트레이 추적\n\n0'
  4. `BTT-RULE:2.0:0011` relevance=미측정 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
  5. `BTT-SOP-001:1.1:0005` relevance=미측정 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제5'
- **q02** hybrid 정답 3위
  1. `BTT-RULE:2.0:0009` relevance=미측정 '문맥: BTT-RULE > 06 광전센서 이벤트와 다중 트레이 추적\n\n0'
  2. `BTT-RULE:2.0:0011` relevance=미측정 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
  3. `BTT-MANUAL:2.0:0004` relevance=미측정 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP01 '
  4. `BTT-RULE:2.0:0010` relevance=미측정 '문맥: BTT-RULE > 06 광전센서 이벤트와 다중 트레이 추적\n\n0'
  5. `BTT-MANUAL:2.0:0006` relevance=미측정 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP02 '
- **q02** reranked 정답 1위
  1. `BTT-MANUAL:2.0:0004` relevance=0.9868 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP01 '
  2. `BTT-RULE:2.0:0011` relevance=0.8017 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
  3. `BTT-RULE:2.0:0010` relevance=0.6020 '문맥: BTT-RULE > 06 광전센서 이벤트와 다중 트레이 추적\n\n0'
  4. `BTT-RULE:2.0:0009` relevance=0.5081 '문맥: BTT-RULE > 06 광전센서 이벤트와 다중 트레이 추적\n\n0'
  5. `BTT-MANUAL:2.0:0006` relevance=0.2468 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP02 '
- **q03** dense 정답 2위
  1. `BTT-MANUAL:2.0:0004` relevance=미측정 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP01 '
  2. `BTT-MANUAL:2.0:0023` relevance=미측정 '문맥: BTT-MANUAL > 12 기계 원인별 추가 점검\n\n12 기계 '
  3. `BTT-MANUAL:2.0:0006` relevance=미측정 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP02 '
  4. `BTT-SOP-001:1.1:0001` relevance=미측정 '문맥: BTT-SOP-001 > 제1장 총칙\n\n제1조(목적)\n\n이 규정은'
  5. `BTT-MANUAL:2.0:0024` relevance=미측정 '문맥: BTT-MANUAL > 12 기계 원인별 추가 점검\n\n12 기계 '
- **q03** hybrid 정답 2위
  1. `BTT-MANUAL:2.0:0004` relevance=미측정 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP01 '
  2. `BTT-MANUAL:2.0:0006` relevance=미측정 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP02 '
  3. `BTT-MANUAL:2.0:0023` relevance=미측정 '문맥: BTT-MANUAL > 12 기계 원인별 추가 점검\n\n12 기계 '
  4. `BTT-SOP-001:1.1:0002` relevance=미측정 '문맥: BTT-SOP-001 > 제1장 총칙\n\n제2조(적용 범위 및 적용'
  5. `BTT-SOP-001:1.1:0020` relevance=미측정 '문맥: BTT-SOP-001 > 제5장 설비 방호 및 유지관리\n\n제16조'
- **q03** reranked 정답 1위
  1. `BTT-MANUAL:2.0:0006` relevance=0.3708 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP02 '
  2. `BTT-MANUAL:2.0:0023` relevance=0.2433 '문맥: BTT-MANUAL > 12 기계 원인별 추가 점검\n\n12 기계 '
  3. `BTT-MANUAL:2.0:0004` relevance=0.1563 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP01 '
  4. `BTT-MANUAL:2.0:0012` relevance=0.0689 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  5. `BTT-MANUAL:2.0:0001` relevance=0.0490 '문맥: BTT-MANUAL > 01 공통 대응·역할·우선순위\n\n01 공통'
- **q04** dense 정답 1위
  1. `BTT-MANUAL:2.0:0007` relevance=미측정 '문맥: BTT-MANUAL > 04 기동·속도·DC 입력전류 대응\n\n04'
  2. `BTT-RULE:2.0:0011` relevance=미측정 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
  3. `BTT-MANUAL:2.0:0002` relevance=미측정 '문맥: BTT-MANUAL > 02 이송·광전 코드 빠른 조회\n\n02 이'
  4. `BTT-MANUAL:2.0:0008` relevance=미측정 '문맥: BTT-MANUAL > 04 기동·속도·DC 입력전류 대응\n\n04'
  5. `BTT-MANUAL:2.0:0012` relevance=미측정 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
- **q04** hybrid 정답 1위
  1. `BTT-MANUAL:2.0:0007` relevance=미측정 '문맥: BTT-MANUAL > 04 기동·속도·DC 입력전류 대응\n\n04'
  2. `BTT-RULE:2.0:0007` relevance=미측정 '문맥: BTT-RULE > 05 운전 조건·모터 구동부 룰\n\n05 운전 '
  3. `BTT-MANUAL:2.0:0008` relevance=미측정 '문맥: BTT-MANUAL > 04 기동·속도·DC 입력전류 대응\n\n04'
  4. `BTT-RULE:2.0:0011` relevance=미측정 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
  5. `BTT-MANUAL:2.0:0002` relevance=미측정 '문맥: BTT-MANUAL > 02 이송·광전 코드 빠른 조회\n\n02 이'
- **q04** reranked 정답 1위
  1. `BTT-MANUAL:2.0:0007` relevance=0.9835 '문맥: BTT-MANUAL > 04 기동·속도·DC 입력전류 대응\n\n04'
  2. `BTT-RULE:2.0:0007` relevance=0.9464 '문맥: BTT-RULE > 05 운전 조건·모터 구동부 룰\n\n05 운전 '
  3. `BTT-MANUAL:2.0:0015` relevance=0.9266 '문맥: BTT-MANUAL > 08 복구·재기동·사건 기록\n\n08 복구·'
  4. `BTT-MANUAL:2.0:0008` relevance=0.7643 '문맥: BTT-MANUAL > 04 기동·속도·DC 입력전류 대응\n\n04'
  5. `BTT-MANUAL:2.0:0021` relevance=0.7125 '문맥: BTT-MANUAL > 11 보완자료 적용 범위·코드 연결\n\n11'
- **q05** dense 정답 2위
  1. `BTT-RULE:2.0:0008` relevance=미측정 '문맥: BTT-RULE > 05 운전 조건·모터 구동부 룰\n\n05 운전 '
  2. `BTT-MANUAL:2.0:0007` relevance=미측정 '문맥: BTT-MANUAL > 04 기동·속도·DC 입력전류 대응\n\n04'
  3. `BTT-MANUAL:2.0:0023` relevance=미측정 '문맥: BTT-MANUAL > 12 기계 원인별 추가 점검\n\n12 기계 '
  4. `BTT-MANUAL:2.0:0012` relevance=미측정 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  5. `BTT-RULE:2.0:0012` relevance=미측정 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
- **q05** hybrid 정답 4위
  1. `BTT-RULE:2.0:0008` relevance=미측정 '문맥: BTT-RULE > 05 운전 조건·모터 구동부 룰\n\n05 운전 '
  2. `BTT-RULE:2.0:0007` relevance=미측정 '문맥: BTT-RULE > 05 운전 조건·모터 구동부 룰\n\n05 운전 '
  3. `BTT-MANUAL:2.0:0012` relevance=미측정 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  4. `BTT-MANUAL:2.0:0007` relevance=미측정 '문맥: BTT-MANUAL > 04 기동·속도·DC 입력전류 대응\n\n04'
  5. `BTT-RULE:2.0:0004` relevance=미측정 '문맥: BTT-RULE > 03 등급·지속시간·회복 조건\n\n03 등급·지'
- **q05** reranked 정답 1위
  1. `BTT-MANUAL:2.0:0007` relevance=0.4731 '문맥: BTT-MANUAL > 04 기동·속도·DC 입력전류 대응\n\n04'
  2. `BTT-MANUAL:2.0:0023` relevance=0.3926 '문맥: BTT-MANUAL > 12 기계 원인별 추가 점검\n\n12 기계 '
  3. `BTT-RULE:2.0:0007` relevance=0.3652 '문맥: BTT-RULE > 05 운전 조건·모터 구동부 룰\n\n05 운전 '
  4. `BTT-RULE:2.0:0013` relevance=0.3152 '문맥: BTT-RULE > 08 진동·측면 변화·복합 판단\n\n08 진동·'
  5. `BTT-RULE:2.0:0001` relevance=0.2883 '문맥: BTT-RULE > 01 적용 범위와 판정 원칙\n\n01 적용 범위'
- **q06** dense 정답 1위
  1. `BTT-MANUAL:2.0:0012` relevance=미측정 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  2. `BTT-SOP-001:1.1:0019` relevance=미측정 '문맥: BTT-SOP-001 > 제5장 설비 방호 및 유지관리\n\n제15조'
  3. `BTT-RULE:2.0:0007` relevance=미측정 '문맥: BTT-RULE > 05 운전 조건·모터 구동부 룰\n\n05 운전 '
  4. `BTT-RULE:2.0:0008` relevance=미측정 '문맥: BTT-RULE > 05 운전 조건·모터 구동부 룰\n\n05 운전 '
  5. `BTT-MANUAL:2.0:0007` relevance=미측정 '문맥: BTT-MANUAL > 04 기동·속도·DC 입력전류 대응\n\n04'
- **q06** hybrid 정답 3위
  1. `BTT-RULE:2.0:0013` relevance=미측정 '문맥: BTT-RULE > 08 진동·측면 변화·복합 판단\n\n08 진동·'
  2. `BTT-RULE:2.0:0007` relevance=미측정 '문맥: BTT-RULE > 05 운전 조건·모터 구동부 룰\n\n05 운전 '
  3. `BTT-MANUAL:2.0:0012` relevance=미측정 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  4. `BTT-MANUAL:2.0:0011` relevance=미측정 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  5. `BTT-RULE:2.0:0008` relevance=미측정 '문맥: BTT-RULE > 05 운전 조건·모터 구동부 룰\n\n05 운전 '
- **q06** reranked 정답 1위
  1. `BTT-MANUAL:2.0:0012` relevance=0.5739 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  2. `BTT-RULE:2.0:0013` relevance=0.4450 '문맥: BTT-RULE > 08 진동·측면 변화·복합 판단\n\n08 진동·'
  3. `BTT-MANUAL:2.0:0021` relevance=0.3160 '문맥: BTT-MANUAL > 11 보완자료 적용 범위·코드 연결\n\n11'
  4. `BTT-SOP-001:1.1:0019` relevance=0.1618 '문맥: BTT-SOP-001 > 제5장 설비 방호 및 유지관리\n\n제15조'
  5. `BTT-MANUAL:2.0:0023` relevance=0.1259 '문맥: BTT-MANUAL > 12 기계 원인별 추가 점검\n\n12 기계 '
- **q07** dense 정답 1위
  1. `BTT-MANUAL:2.0:0012` relevance=미측정 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  2. `BTT-SOP-001:1.1:0005` relevance=미측정 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제5'
  3. `BTT-RULE:2.0:0012` relevance=미측정 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
  4. `BTT-MANUAL:2.0:0023` relevance=미측정 '문맥: BTT-MANUAL > 12 기계 원인별 추가 점검\n\n12 기계 '
  5. `BTT-SOP-001:1.1:0019` relevance=미측정 '문맥: BTT-SOP-001 > 제5장 설비 방호 및 유지관리\n\n제15조'
- **q07** hybrid 정답 1위
  1. `BTT-MANUAL:2.0:0012` relevance=미측정 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  2. `BTT-MANUAL:2.0:0023` relevance=미측정 '문맥: BTT-MANUAL > 12 기계 원인별 추가 점검\n\n12 기계 '
  3. `BTT-RULE:2.0:0011` relevance=미측정 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
  4. `BTT-SOP-001:1.1:0017` relevance=미측정 '문맥: BTT-SOP-001 > 제5장 설비 방호 및 유지관리\n\n제14조'
  5. `BTT-RULE:2.0:0004` relevance=미측정 '문맥: BTT-RULE > 03 등급·지속시간·회복 조건\n\n03 등급·지'
- **q07** reranked 정답 1위
  1. `BTT-MANUAL:2.0:0012` relevance=0.6653 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  2. `BTT-RULE:2.0:0013` relevance=0.6545 '문맥: BTT-RULE > 08 진동·측면 변화·복합 판단\n\n08 진동·'
  3. `BTT-RULE:2.0:0004` relevance=0.2622 '문맥: BTT-RULE > 03 등급·지속시간·회복 조건\n\n03 등급·지'
  4. `BTT-RULE:2.0:0017` relevance=0.2235 '문맥: BTT-RULE > 10 구현·인수시험·변경 관리\n\n10 구현·인'
  5. `BTT-RULE:2.0:0008` relevance=0.1135 '문맥: BTT-RULE > 05 운전 조건·모터 구동부 룰\n\n05 운전 '
- **q08** dense 정답 1위
  1. `BTT-MANUAL:2.0:0005` relevance=미측정 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP03 '
  2. `BTT-MANUAL:2.0:0023` relevance=미측정 '문맥: BTT-MANUAL > 12 기계 원인별 추가 점검\n\n12 기계 '
  3. `BTT-MANUAL:2.0:0019` relevance=미측정 '문맥: BTT-MANUAL > 10 출처·적용 범위\n\n10 출처·적용 범'
  4. `BTT-RULE:2.0:0019` relevance=미측정 '문맥: BTT-RULE > 11 근거·데이터 출처\n\n11 근거·데이터 출'
  5. `BTT-SOP-001:1.1:0009` relevance=미측정 '문맥: BTT-SOP-001 > 제3장 점검·조치 및 재가동\n\n제8조(점'
- **q08** hybrid 정답 1위
  1. `BTT-MANUAL:2.0:0005` relevance=미측정 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP03 '
  2. `BTT-MANUAL:2.0:0023` relevance=미측정 '문맥: BTT-MANUAL > 12 기계 원인별 추가 점검\n\n12 기계 '
  3. `BTT-RULE:2.0:0009` relevance=미측정 '문맥: BTT-RULE > 06 광전센서 이벤트와 다중 트레이 추적\n\n0'
  4. `BTT-MANUAL:2.0:0019` relevance=미측정 '문맥: BTT-MANUAL > 10 출처·적용 범위\n\n10 출처·적용 범'
  5. `BTT-RULE:2.0:0019` relevance=미측정 '문맥: BTT-RULE > 11 근거·데이터 출처\n\n11 근거·데이터 출'
- **q08** reranked 정답 1위
  1. `BTT-MANUAL:2.0:0005` relevance=0.9800 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP03 '
  2. `BTT-MANUAL:2.0:0019` relevance=0.2703 '문맥: BTT-MANUAL > 10 출처·적용 범위\n\n10 출처·적용 범'
  3. `BTT-RULE:2.0:0019` relevance=0.2078 '문맥: BTT-RULE > 11 근거·데이터 출처\n\n11 근거·데이터 출'
  4. `BTT-MANUAL:2.0:0023` relevance=0.0234 '문맥: BTT-MANUAL > 12 기계 원인별 추가 점검\n\n12 기계 '
- **q09** dense 정답 1위
  1. `BTT-SOP-001:1.1:0007` relevance=미측정 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제7'
  2. `BTT-SOP-001:1.1:0006` relevance=미측정 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제6'
  3. `BTT-SOP-001:1.1:0008` relevance=미측정 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제7'
  4. `BTT-SOP-001:1.1:0009` relevance=미측정 '문맥: BTT-SOP-001 > 제3장 점검·조치 및 재가동\n\n제8조(점'
  5. `BTT-SOP-001:1.1:0005` relevance=미측정 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제5'
- **q09** hybrid 정답 1위
  1. `BTT-SOP-001:1.1:0007` relevance=미측정 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제7'
  2. `BTT-SOP-001:1.1:0006` relevance=미측정 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제6'
  3. `BTT-SOP-001:1.1:0008` relevance=미측정 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제7'
  4. `BTT-SOP-001:1.1:0005` relevance=미측정 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제5'
  5. `BTT-SOP-001:1.1:0000` relevance=미측정 '문맥: BTT-SOP-001\n\n| BATTERY TRAY TRANSFER'
- **q09** reranked 정답 1위
  1. `BTT-SOP-001:1.1:0007` relevance=0.8986 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제7'
  2. `BTT-SOP-001:1.1:0006` relevance=0.8629 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제6'
  3. `BTT-SOP-001:1.1:0027` relevance=0.7243 '문맥: BTT-SOP-001 > 제7장 RAG 등록 및 해석\n\n별지 제1'
  4. `BTT-SOP-001:1.1:0005` relevance=0.6315 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제5'
  5. `BTT-SOP-001:1.1:0008` relevance=0.5619 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제7'
- **q10** dense 정답 1위
  1. `BTT-SOP-001:1.1:0011` relevance=미측정 '문맥: BTT-SOP-001 > 제3장 점검·조치 및 재가동\n\n제10조('
  2. `BTT-SOP-001:1.1:0012` relevance=미측정 '문맥: BTT-SOP-001 > 제3장 점검·조치 및 재가동\n\n제10조('
  3. `BTT-SOP-001:1.1:0003` relevance=미측정 '문맥: BTT-SOP-001 > 제1장 총칙\n\n제3조(역할과 권한)\n\n①'
  4. `BTT-SOP-001:1.1:0010` relevance=미측정 '문맥: BTT-SOP-001 > 제3장 점검·조치 및 재가동\n\n제9조(일'
  5. `BTT-MANUAL:2.0:0025` relevance=미측정 '문맥: BTT-MANUAL > 13 정비 후 검증·이력 연결\n\n13 정비'
- **q10** hybrid 정답 1위
  1. `BTT-SOP-001:1.1:0011` relevance=미측정 '문맥: BTT-SOP-001 > 제3장 점검·조치 및 재가동\n\n제10조('
  2. `BTT-SOP-001:1.1:0010` relevance=미측정 '문맥: BTT-SOP-001 > 제3장 점검·조치 및 재가동\n\n제9조(일'
  3. `BTT-SOP-001:1.1:0012` relevance=미측정 '문맥: BTT-SOP-001 > 제3장 점검·조치 및 재가동\n\n제10조('
  4. `BTT-MANUAL:2.0:0026` relevance=미측정 '문맥: BTT-MANUAL > 13 정비 후 검증·이력 연결\n\n13 정비'
  5. `BTT-MANUAL:2.0:0025` relevance=미측정 '문맥: BTT-MANUAL > 13 정비 후 검증·이력 연결\n\n13 정비'
- **q10** reranked 정답 2위
  1. `BTT-MANUAL:2.0:0001` relevance=0.7968 '문맥: BTT-MANUAL > 01 공통 대응·역할·우선순위\n\n01 공통'
  2. `BTT-SOP-001:1.1:0011` relevance=0.7172 '문맥: BTT-SOP-001 > 제3장 점검·조치 및 재가동\n\n제10조('
  3. `BTT-SOP-001:1.1:0012` relevance=0.6378 '문맥: BTT-SOP-001 > 제3장 점검·조치 및 재가동\n\n제10조('
  4. `BTT-SOP-001:1.1:0003` relevance=0.1972 '문맥: BTT-SOP-001 > 제1장 총칙\n\n제3조(역할과 권한)\n\n①'
  5. `BTT-SOP-001:1.1:0010` relevance=0.1754 '문맥: BTT-SOP-001 > 제3장 점검·조치 및 재가동\n\n제9조(일'
- **q11** dense 정답 1위
  1. `BTT-RULE:2.0:0011` relevance=미측정 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
  2. `BTT-RULE:2.0:0012` relevance=미측정 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
  3. `BTT-RULE:2.0:0001` relevance=미측정 '문맥: BTT-RULE > 01 적용 범위와 판정 원칙\n\n01 적용 범위'
  4. `BTT-RULE:2.0:0009` relevance=미측정 '문맥: BTT-RULE > 06 광전센서 이벤트와 다중 트레이 추적\n\n0'
  5. `BTT-MANUAL:2.0:0002` relevance=미측정 '문맥: BTT-MANUAL > 02 이송·광전 코드 빠른 조회\n\n02 이'
- **q11** hybrid 정답 1위
  1. `BTT-RULE:2.0:0011` relevance=미측정 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
  2. `BTT-RULE:2.0:0012` relevance=미측정 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
  3. `BTT-RULE:2.0:0001` relevance=미측정 '문맥: BTT-RULE > 01 적용 범위와 판정 원칙\n\n01 적용 범위'
  4. `BTT-MANUAL:2.0:0002` relevance=미측정 '문맥: BTT-MANUAL > 02 이송·광전 코드 빠른 조회\n\n02 이'
  5. `BTT-RULE:2.0:0000` relevance=미측정 '문맥: BTT-RULE\n\n| BATTERY TRAY TRANSFER / '
- **q11** reranked 정답 1위
  1. `BTT-RULE:2.0:0001` relevance=0.9864 '문맥: BTT-RULE > 01 적용 범위와 판정 원칙\n\n01 적용 범위'
  2. `BTT-RULE:2.0:0012` relevance=0.9451 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
  3. `BTT-RULE:2.0:0011` relevance=0.9434 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
  4. `BTT-RULE:2.0:0009` relevance=0.9426 '문맥: BTT-RULE > 06 광전센서 이벤트와 다중 트레이 추적\n\n0'
  5. `BTT-MANUAL:2.0:0020` relevance=0.7335 '문맥: BTT-MANUAL > 10 출처·적용 범위\n\n10 출처·적용 범'
- **q12** dense 정답 4위
  1. `BTT-SOP-001:1.1:0004` relevance=미측정 '문맥: BTT-SOP-001 > 제1장 총칙\n\n제4조(센서 관측의 한계)'
  2. `BTT-RULE:2.0:0001` relevance=미측정 '문맥: BTT-RULE > 01 적용 범위와 판정 원칙\n\n01 적용 범위'
  3. `BTT-RULE:2.0:0006` relevance=미측정 '문맥: BTT-RULE > 04 수치 룰 임계값 원장\n\n04 수치 룰 임'
  4. `BTT-RULE:2.0:0004` relevance=미측정 '문맥: BTT-RULE > 03 등급·지속시간·회복 조건\n\n03 등급·지'
  5. `BTT-RULE:2.0:0002` relevance=미측정 '문맥: BTT-RULE > 02 15컬럼 데이터 계약\n\n02 15컬럼 데'
- **q12** hybrid 정답 1위
  1. `BTT-RULE:2.0:0004` relevance=미측정 '문맥: BTT-RULE > 03 등급·지속시간·회복 조건\n\n03 등급·지'
  2. `BTT-RULE:2.0:0001` relevance=미측정 '문맥: BTT-RULE > 01 적용 범위와 판정 원칙\n\n01 적용 범위'
  3. `BTT-RULE:2.0:0012` relevance=미측정 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
  4. `BTT-RULE:2.0:0000` relevance=미측정 '문맥: BTT-RULE\n\n| BATTERY TRAY TRANSFER / '
  5. `BTT-SOP-001:1.1:0009` relevance=미측정 '문맥: BTT-SOP-001 > 제3장 점검·조치 및 재가동\n\n제8조(점'
- **q12** reranked 정답 4위
  1. `BTT-RULE:2.0:0012` relevance=0.3956 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
  2. `BTT-RULE:2.0:0001` relevance=0.3829 '문맥: BTT-RULE > 01 적용 범위와 판정 원칙\n\n01 적용 범위'
  3. `BTT-SOP-001:1.1:0016` relevance=0.3235 '문맥: BTT-SOP-001 > 제4장 업무 상태·데이터 및 보안\n\n제1'
  4. `BTT-RULE:2.0:0004` relevance=0.3107 '문맥: BTT-RULE > 03 등급·지속시간·회복 조건\n\n03 등급·지'
  5. `BTT-RULE:2.0:0000` relevance=0.2783 '문맥: BTT-RULE\n\n| BATTERY TRAY TRANSFER / '
- **i01** dense 정답 1위
  1. `BTT-MANUAL:2.0:0005` relevance=미측정 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP03 '
  2. `BTT-RULE:2.0:0001` relevance=미측정 '문맥: BTT-RULE > 01 적용 범위와 판정 원칙\n\n01 적용 범위'
  3. `BTT-RULE:2.0:0017` relevance=미측정 '문맥: BTT-RULE > 10 구현·인수시험·변경 관리\n\n10 구현·인'
  4. `BTT-MANUAL:2.0:0004` relevance=미측정 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP01 '
  5. `BTT-MANUAL:2.0:0006` relevance=미측정 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP02 '
- **i01** hybrid 정답 1위
  1. `BTT-MANUAL:2.0:0005` relevance=미측정 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP03 '
  2. `BTT-RULE:2.0:0017` relevance=미측정 '문맥: BTT-RULE > 10 구현·인수시험·변경 관리\n\n10 구현·인'
  3. `BTT-RULE:2.0:0001` relevance=미측정 '문맥: BTT-RULE > 01 적용 범위와 판정 원칙\n\n01 적용 범위'
  4. `BTT-RULE:2.0:0011` relevance=미측정 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
  5. `BTT-SOP-001:1.1:0005` relevance=미측정 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제5'
- **i01** reranked 정답 1위
  1. `BTT-MANUAL:2.0:0005` relevance=0.9938 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP03 '
  2. `BTT-MANUAL:2.0:0015` relevance=0.8981 '문맥: BTT-MANUAL > 08 복구·재기동·사건 기록\n\n08 복구·'
  3. `BTT-MANUAL:2.0:0021` relevance=0.6945 '문맥: BTT-MANUAL > 11 보완자료 적용 범위·코드 연결\n\n11'
  4. `BTT-RULE:2.0:0011` relevance=0.6769 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
  5. `BTT-MANUAL:2.0:0002` relevance=0.6207 '문맥: BTT-MANUAL > 02 이송·광전 코드 빠른 조회\n\n02 이'
- **i02** dense 정답 3위
  1. `BTT-RULE:2.0:0011` relevance=미측정 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
  2. `BTT-RULE:2.0:0012` relevance=미측정 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
  3. `BTT-MANUAL:2.0:0004` relevance=미측정 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP01 '
  4. `BTT-MANUAL:2.0:0002` relevance=미측정 '문맥: BTT-MANUAL > 02 이송·광전 코드 빠른 조회\n\n02 이'
  5. `BTT-MANUAL:2.0:0006` relevance=미측정 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP02 '
- **i02** hybrid 정답 3위
  1. `BTT-RULE:2.0:0011` relevance=미측정 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
  2. `BTT-RULE:2.0:0012` relevance=미측정 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
  3. `BTT-MANUAL:2.0:0004` relevance=미측정 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP01 '
  4. `BTT-MANUAL:2.0:0002` relevance=미측정 '문맥: BTT-MANUAL > 02 이송·광전 코드 빠른 조회\n\n02 이'
  5. `BTT-SOP-001:1.1:0005` relevance=미측정 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제5'
- **i02** reranked 정답 1위
  1. `BTT-MANUAL:2.0:0004` relevance=0.9324 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP01 '
  2. `BTT-MANUAL:2.0:0002` relevance=0.7705 '문맥: BTT-MANUAL > 02 이송·광전 코드 빠른 조회\n\n02 이'
  3. `BTT-RULE:2.0:0011` relevance=0.6696 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
  4. `BTT-MANUAL:2.0:0015` relevance=0.5709 '문맥: BTT-MANUAL > 08 복구·재기동·사건 기록\n\n08 복구·'
  5. `BTT-MANUAL:2.0:0006` relevance=0.4911 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP02 '
- **i03** dense 정답 1위
  1. `BTT-MANUAL:2.0:0007` relevance=미측정 '문맥: BTT-MANUAL > 04 기동·속도·DC 입력전류 대응\n\n04'
  2. `BTT-RULE:2.0:0008` relevance=미측정 '문맥: BTT-RULE > 05 운전 조건·모터 구동부 룰\n\n05 운전 '
  3. `BTT-MANUAL:2.0:0009` relevance=미측정 '문맥: BTT-MANUAL > 05 공급전압·외함 온도 대응\n\n05 공급'
  4. `BTT-MANUAL:2.0:0012` relevance=미측정 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  5. `BTT-MANUAL:2.0:0008` relevance=미측정 '문맥: BTT-MANUAL > 04 기동·속도·DC 입력전류 대응\n\n04'
- **i03** hybrid 정답 1위
  1. `BTT-MANUAL:2.0:0007` relevance=미측정 '문맥: BTT-MANUAL > 04 기동·속도·DC 입력전류 대응\n\n04'
  2. `BTT-MANUAL:2.0:0012` relevance=미측정 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  3. `BTT-RULE:2.0:0007` relevance=미측정 '문맥: BTT-RULE > 05 운전 조건·모터 구동부 룰\n\n05 운전 '
  4. `BTT-RULE:2.0:0008` relevance=미측정 '문맥: BTT-RULE > 05 운전 조건·모터 구동부 룰\n\n05 운전 '
  5. `BTT-MANUAL:2.0:0008` relevance=미측정 '문맥: BTT-MANUAL > 04 기동·속도·DC 입력전류 대응\n\n04'
- **i03** reranked 정답 1위
  1. `BTT-MANUAL:2.0:0007` relevance=0.5942 '문맥: BTT-MANUAL > 04 기동·속도·DC 입력전류 대응\n\n04'
  2. `BTT-MANUAL:2.0:0015` relevance=0.5535 '문맥: BTT-MANUAL > 08 복구·재기동·사건 기록\n\n08 복구·'
  3. `BTT-MANUAL:2.0:0006` relevance=0.4264 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP02 '
  4. `BTT-RULE:2.0:0017` relevance=0.4106 '문맥: BTT-RULE > 10 구현·인수시험·변경 관리\n\n10 구현·인'
  5. `BTT-RULE:2.0:0007` relevance=0.3236 '문맥: BTT-RULE > 05 운전 조건·모터 구동부 룰\n\n05 운전 '
- **i04** dense 정답 1위
  1. `BTT-MANUAL:2.0:0012` relevance=미측정 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  2. `BTT-RULE:2.0:0013` relevance=미측정 '문맥: BTT-RULE > 08 진동·측면 변화·복합 판단\n\n08 진동·'
  3. `BTT-MANUAL:2.0:0011` relevance=미측정 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  4. `BTT-MANUAL:2.0:0007` relevance=미측정 '문맥: BTT-MANUAL > 04 기동·속도·DC 입력전류 대응\n\n04'
  5. `BTT-MANUAL:2.0:0023` relevance=미측정 '문맥: BTT-MANUAL > 12 기계 원인별 추가 점검\n\n12 기계 '
- **i04** hybrid 정답 1위
  1. `BTT-MANUAL:2.0:0012` relevance=미측정 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  2. `BTT-RULE:2.0:0013` relevance=미측정 '문맥: BTT-RULE > 08 진동·측면 변화·복합 판단\n\n08 진동·'
  3. `BTT-MANUAL:2.0:0011` relevance=미측정 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  4. `BTT-RULE:2.0:0014` relevance=미측정 '문맥: BTT-RULE > 08 진동·측면 변화·복합 판단\n\n08 진동·'
  5. `BTT-RULE:2.0:0001` relevance=미측정 '문맥: BTT-RULE > 01 적용 범위와 판정 원칙\n\n01 적용 범위'
- **i04** reranked 정답 1위
  1. `BTT-MANUAL:2.0:0012` relevance=0.8581 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  2. `BTT-RULE:2.0:0013` relevance=0.5780 '문맥: BTT-RULE > 08 진동·측면 변화·복합 판단\n\n08 진동·'
  3. `BTT-MANUAL:2.0:0001` relevance=0.4591 '문맥: BTT-MANUAL > 01 공통 대응·역할·우선순위\n\n01 공통'
  4. `BTT-MANUAL:2.0:0021` relevance=0.4410 '문맥: BTT-MANUAL > 11 보완자료 적용 범위·코드 연결\n\n11'
  5. `BTT-MANUAL:2.0:0011` relevance=0.4343 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
- **i05** dense 정답 1위
  1. `BTT-MANUAL:2.0:0012` relevance=미측정 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  2. `BTT-RULE:2.0:0013` relevance=미측정 '문맥: BTT-RULE > 08 진동·측면 변화·복합 판단\n\n08 진동·'
  3. `BTT-MANUAL:2.0:0007` relevance=미측정 '문맥: BTT-MANUAL > 04 기동·속도·DC 입력전류 대응\n\n04'
  4. `BTT-SOP-001:1.1:0005` relevance=미측정 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제5'
  5. `BTT-SOP-001:1.1:0019` relevance=미측정 '문맥: BTT-SOP-001 > 제5장 설비 방호 및 유지관리\n\n제15조'
- **i05** hybrid 정답 1위
  1. `BTT-MANUAL:2.0:0012` relevance=미측정 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  2. `BTT-RULE:2.0:0013` relevance=미측정 '문맥: BTT-RULE > 08 진동·측면 변화·복합 판단\n\n08 진동·'
  3. `BTT-SOP-001:1.1:0005` relevance=미측정 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제5'
  4. `BTT-RULE:2.0:0011` relevance=미측정 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
  5. `BTT-MANUAL:2.0:0011` relevance=미측정 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
- **i05** reranked 정답 1위
  1. `BTT-MANUAL:2.0:0012` relevance=0.8457 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  2. `BTT-RULE:2.0:0013` relevance=0.5490 '문맥: BTT-RULE > 08 진동·측면 변화·복합 판단\n\n08 진동·'
  3. `BTT-MANUAL:2.0:0001` relevance=0.4491 '문맥: BTT-MANUAL > 01 공통 대응·역할·우선순위\n\n01 공통'
  4. `BTT-MANUAL:2.0:0021` relevance=0.3351 '문맥: BTT-MANUAL > 11 보완자료 적용 범위·코드 연결\n\n11'
  5. `BTT-MANUAL:2.0:0015` relevance=0.2159 '문맥: BTT-MANUAL > 08 복구·재기동·사건 기록\n\n08 복구·'
- **i06** dense 정답 1위
  1. `BTT-MANUAL:2.0:0012` relevance=미측정 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  2. `BTT-RULE:2.0:0014` relevance=미측정 '문맥: BTT-RULE > 08 진동·측면 변화·복합 판단\n\n08 진동·'
  3. `BTT-RULE:2.0:0013` relevance=미측정 '문맥: BTT-RULE > 08 진동·측면 변화·복합 판단\n\n08 진동·'
  4. `BTT-MANUAL:2.0:0011` relevance=미측정 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  5. `BTT-MANUAL:2.0:0006` relevance=미측정 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP02 '
- **i06** hybrid 정답 1위
  1. `BTT-MANUAL:2.0:0012` relevance=미측정 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  2. `BTT-RULE:2.0:0013` relevance=미측정 '문맥: BTT-RULE > 08 진동·측면 변화·복합 판단\n\n08 진동·'
  3. `BTT-MANUAL:2.0:0011` relevance=미측정 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  4. `BTT-RULE:2.0:0014` relevance=미측정 '문맥: BTT-RULE > 08 진동·측면 변화·복합 판단\n\n08 진동·'
  5. `BTT-MANUAL:2.0:0015` relevance=미측정 '문맥: BTT-MANUAL > 08 복구·재기동·사건 기록\n\n08 복구·'
- **i06** reranked 정답 1위
  1. `BTT-MANUAL:2.0:0012` relevance=0.9596 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  2. `BTT-MANUAL:2.0:0015` relevance=0.8113 '문맥: BTT-MANUAL > 08 복구·재기동·사건 기록\n\n08 복구·'
  3. `BTT-RULE:2.0:0013` relevance=0.7378 '문맥: BTT-RULE > 08 진동·측면 변화·복합 판단\n\n08 진동·'
  4. `BTT-MANUAL:2.0:0021` relevance=0.6901 '문맥: BTT-MANUAL > 11 보완자료 적용 범위·코드 연결\n\n11'
  5. `BTT-MANUAL:2.0:0011` relevance=0.5768 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
- **i07** dense 정답 1위
  1. `BTT-MANUAL:2.0:0007` relevance=미측정 '문맥: BTT-MANUAL > 04 기동·속도·DC 입력전류 대응\n\n04'
  2. `BTT-SOP-001:1.1:0009` relevance=미측정 '문맥: BTT-SOP-001 > 제3장 점검·조치 및 재가동\n\n제8조(점'
  3. `BTT-SOP-001:1.1:0005` relevance=미측정 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제5'
  4. `BTT-RULE:2.0:0014` relevance=미측정 '문맥: BTT-RULE > 08 진동·측면 변화·복합 판단\n\n08 진동·'
  5. `BTT-RULE:2.0:0007` relevance=미측정 '문맥: BTT-RULE > 05 운전 조건·모터 구동부 룰\n\n05 운전 '
- **i07** hybrid 정답 1위
  1. `BTT-MANUAL:2.0:0007` relevance=미측정 '문맥: BTT-MANUAL > 04 기동·속도·DC 입력전류 대응\n\n04'
  2. `BTT-RULE:2.0:0007` relevance=미측정 '문맥: BTT-RULE > 05 운전 조건·모터 구동부 룰\n\n05 운전 '
  3. `BTT-SOP-001:1.1:0005` relevance=미측정 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제5'
  4. `BTT-MANUAL:2.0:0008` relevance=미측정 '문맥: BTT-MANUAL > 04 기동·속도·DC 입력전류 대응\n\n04'
  5. `BTT-RULE:2.0:0014` relevance=미측정 '문맥: BTT-RULE > 08 진동·측면 변화·복합 판단\n\n08 진동·'
- **i07** reranked 정답 2위
  1. `BTT-MANUAL:2.0:0015` relevance=0.8905 '문맥: BTT-MANUAL > 08 복구·재기동·사건 기록\n\n08 복구·'
  2. `BTT-MANUAL:2.0:0007` relevance=0.8724 '문맥: BTT-MANUAL > 04 기동·속도·DC 입력전류 대응\n\n04'
  3. `BTT-MANUAL:2.0:0001` relevance=0.6346 '문맥: BTT-MANUAL > 01 공통 대응·역할·우선순위\n\n01 공통'
  4. `BTT-RULE:2.0:0007` relevance=0.6139 '문맥: BTT-RULE > 05 운전 조건·모터 구동부 룰\n\n05 운전 '
  5. `BTT-MANUAL:2.0:0021` relevance=0.6107 '문맥: BTT-MANUAL > 11 보완자료 적용 범위·코드 연결\n\n11'
- **i08** dense 정답 1위
  1. `BTT-MANUAL:2.0:0007` relevance=미측정 '문맥: BTT-MANUAL > 04 기동·속도·DC 입력전류 대응\n\n04'
  2. `BTT-RULE:2.0:0008` relevance=미측정 '문맥: BTT-RULE > 05 운전 조건·모터 구동부 룰\n\n05 운전 '
  3. `BTT-MANUAL:2.0:0012` relevance=미측정 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  4. `BTT-RULE:2.0:0004` relevance=미측정 '문맥: BTT-RULE > 03 등급·지속시간·회복 조건\n\n03 등급·지'
  5. `BTT-RULE:2.0:0007` relevance=미측정 '문맥: BTT-RULE > 05 운전 조건·모터 구동부 룰\n\n05 운전 '
- **i08** hybrid 정답 1위
  1. `BTT-MANUAL:2.0:0007` relevance=미측정 '문맥: BTT-MANUAL > 04 기동·속도·DC 입력전류 대응\n\n04'
  2. `BTT-RULE:2.0:0007` relevance=미측정 '문맥: BTT-RULE > 05 운전 조건·모터 구동부 룰\n\n05 운전 '
  3. `BTT-RULE:2.0:0004` relevance=미측정 '문맥: BTT-RULE > 03 등급·지속시간·회복 조건\n\n03 등급·지'
  4. `BTT-RULE:2.0:0008` relevance=미측정 '문맥: BTT-RULE > 05 운전 조건·모터 구동부 룰\n\n05 운전 '
  5. `BTT-RULE:2.0:0011` relevance=미측정 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
- **i08** reranked 정답 1위
  1. `BTT-MANUAL:2.0:0007` relevance=0.6274 '문맥: BTT-MANUAL > 04 기동·속도·DC 입력전류 대응\n\n04'
  2. `BTT-MANUAL:2.0:0004` relevance=0.5635 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP01 '
  3. `BTT-MANUAL:2.0:0006` relevance=0.5062 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP02 '
  4. `BTT-MANUAL:2.0:0001` relevance=0.4300 '문맥: BTT-MANUAL > 01 공통 대응·역할·우선순위\n\n01 공통'
  5. `BTT-RULE:2.0:0007` relevance=0.4213 '문맥: BTT-RULE > 05 운전 조건·모터 구동부 룰\n\n05 운전 '
- **i09** dense 정답 1위
  1. `BTT-MANUAL:2.0:0005` relevance=미측정 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP03 '
  2. `BTT-SOP-001:1.1:0004` relevance=미측정 '문맥: BTT-SOP-001 > 제1장 총칙\n\n제4조(센서 관측의 한계)'
  3. `BTT-RULE:2.0:0001` relevance=미측정 '문맥: BTT-RULE > 01 적용 범위와 판정 원칙\n\n01 적용 범위'
  4. `BTT-MANUAL:2.0:0006` relevance=미측정 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP02 '
  5. `BTT-RULE:2.0:0011` relevance=미측정 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
- **i09** hybrid 정답 1위
  1. `BTT-MANUAL:2.0:0005` relevance=미측정 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP03 '
  2. `BTT-RULE:2.0:0011` relevance=미측정 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
  3. `BTT-MANUAL:2.0:0002` relevance=미측정 '문맥: BTT-MANUAL > 02 이송·광전 코드 빠른 조회\n\n02 이'
  4. `BTT-MANUAL:2.0:0006` relevance=미측정 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP02 '
  5. `BTT-RULE:2.0:0017` relevance=미측정 '문맥: BTT-RULE > 10 구현·인수시험·변경 관리\n\n10 구현·인'
- **i09** reranked 정답 1위
  1. `BTT-MANUAL:2.0:0005` relevance=0.9908 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP03 '
  2. `BTT-MANUAL:2.0:0015` relevance=0.9066 '문맥: BTT-MANUAL > 08 복구·재기동·사건 기록\n\n08 복구·'
  3. `BTT-MANUAL:2.0:0021` relevance=0.7592 '문맥: BTT-MANUAL > 11 보완자료 적용 범위·코드 연결\n\n11'
  4. `BTT-MANUAL:2.0:0002` relevance=0.6963 '문맥: BTT-MANUAL > 02 이송·광전 코드 빠른 조회\n\n02 이'
  5. `BTT-RULE:2.0:0011` relevance=0.6558 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
- **i10** dense 정답 2위
  1. `BTT-RULE:2.0:0012` relevance=미측정 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
  2. `BTT-MANUAL:2.0:0006` relevance=미측정 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP02 '
  3. `BTT-RULE:2.0:0011` relevance=미측정 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
  4. `BTT-RULE:2.0:0001` relevance=미측정 '문맥: BTT-RULE > 01 적용 범위와 판정 원칙\n\n01 적용 범위'
  5. `BTT-SOP-001:1.1:0005` relevance=미측정 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제5'
- **i10** hybrid 정답 3위
  1. `BTT-RULE:2.0:0012` relevance=미측정 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
  2. `BTT-RULE:2.0:0011` relevance=미측정 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
  3. `BTT-MANUAL:2.0:0006` relevance=미측정 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP02 '
  4. `BTT-RULE:2.0:0001` relevance=미측정 '문맥: BTT-RULE > 01 적용 범위와 판정 원칙\n\n01 적용 범위'
  5. `BTT-SOP-001:1.1:0005` relevance=미측정 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제5'
- **i10** reranked 정답 1위
  1. `BTT-MANUAL:2.0:0006` relevance=0.9461 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP02 '
  2. `BTT-RULE:2.0:0012` relevance=0.7028 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
  3. `BTT-MANUAL:2.0:0001` relevance=0.6315 '문맥: BTT-MANUAL > 01 공통 대응·역할·우선순위\n\n01 공통'
  4. `BTT-MANUAL:2.0:0002` relevance=0.5541 '문맥: BTT-MANUAL > 02 이송·광전 코드 빠른 조회\n\n02 이'
  5. `BTT-RULE:2.0:0011` relevance=0.4980 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
- **i11** dense 정답 1위
  1. `BTT-MANUAL:2.0:0012` relevance=미측정 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  2. `BTT-RULE:2.0:0013` relevance=미측정 '문맥: BTT-RULE > 08 진동·측면 변화·복합 판단\n\n08 진동·'
  3. `BTT-MANUAL:2.0:0011` relevance=미측정 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  4. `BTT-MANUAL:2.0:0007` relevance=미측정 '문맥: BTT-MANUAL > 04 기동·속도·DC 입력전류 대응\n\n04'
  5. `BTT-MANUAL:2.0:0023` relevance=미측정 '문맥: BTT-MANUAL > 12 기계 원인별 추가 점검\n\n12 기계 '
- **i11** hybrid 정답 1위
  1. `BTT-MANUAL:2.0:0012` relevance=미측정 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  2. `BTT-RULE:2.0:0013` relevance=미측정 '문맥: BTT-RULE > 08 진동·측면 변화·복합 판단\n\n08 진동·'
  3. `BTT-MANUAL:2.0:0011` relevance=미측정 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  4. `BTT-SOP-001:1.1:0005` relevance=미측정 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제5'
  5. `BTT-RULE:2.0:0001` relevance=미측정 '문맥: BTT-RULE > 01 적용 범위와 판정 원칙\n\n01 적용 범위'
- **i11** reranked 정답 1위
  1. `BTT-MANUAL:2.0:0012` relevance=0.9064 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  2. `BTT-RULE:2.0:0013` relevance=0.6524 '문맥: BTT-RULE > 08 진동·측면 변화·복합 판단\n\n08 진동·'
  3. `BTT-MANUAL:2.0:0021` relevance=0.6128 '문맥: BTT-MANUAL > 11 보완자료 적용 범위·코드 연결\n\n11'
  4. `BTT-MANUAL:2.0:0001` relevance=0.4477 '문맥: BTT-MANUAL > 01 공통 대응·역할·우선순위\n\n01 공통'
  5. `BTT-MANUAL:2.0:0015` relevance=0.3504 '문맥: BTT-MANUAL > 08 복구·재기동·사건 기록\n\n08 복구·'
- **i12** dense 정답 1위
  1. `BTT-MANUAL:2.0:0012` relevance=미측정 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  2. `BTT-RULE:2.0:0013` relevance=미측정 '문맥: BTT-RULE > 08 진동·측면 변화·복합 판단\n\n08 진동·'
  3. `BTT-MANUAL:2.0:0023` relevance=미측정 '문맥: BTT-MANUAL > 12 기계 원인별 추가 점검\n\n12 기계 '
  4. `BTT-SOP-001:1.1:0005` relevance=미측정 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제5'
  5. `BTT-RULE:2.0:0014` relevance=미측정 '문맥: BTT-RULE > 08 진동·측면 변화·복합 판단\n\n08 진동·'
- **i12** hybrid 정답 1위
  1. `BTT-MANUAL:2.0:0012` relevance=미측정 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  2. `BTT-RULE:2.0:0013` relevance=미측정 '문맥: BTT-RULE > 08 진동·측면 변화·복합 판단\n\n08 진동·'
  3. `BTT-MANUAL:2.0:0011` relevance=미측정 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  4. `BTT-SOP-001:1.1:0005` relevance=미측정 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제5'
  5. `BTT-RULE:2.0:0011` relevance=미측정 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
- **i12** reranked 정답 1위
  1. `BTT-MANUAL:2.0:0012` relevance=0.9261 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  2. `BTT-MANUAL:2.0:0015` relevance=0.8523 '문맥: BTT-MANUAL > 08 복구·재기동·사건 기록\n\n08 복구·'
  3. `BTT-RULE:2.0:0013` relevance=0.7097 '문맥: BTT-RULE > 08 진동·측면 변화·복합 판단\n\n08 진동·'
  4. `BTT-MANUAL:2.0:0021` relevance=0.4814 '문맥: BTT-MANUAL > 11 보완자료 적용 범위·코드 연결\n\n11'
  5. `BTT-MANUAL:2.0:0001` relevance=0.3673 '문맥: BTT-MANUAL > 01 공통 대응·역할·우선순위\n\n01 공통'
- **q13** dense 정답 1위
  1. `BTT-MANUAL:2.0:0007` relevance=미측정 '문맥: BTT-MANUAL > 04 기동·속도·DC 입력전류 대응\n\n04'
  2. `BTT-MANUAL:2.0:0012` relevance=미측정 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  3. `BTT-RULE:2.0:0008` relevance=미측정 '문맥: BTT-RULE > 05 운전 조건·모터 구동부 룰\n\n05 운전 '
  4. `BTT-RULE:2.0:0007` relevance=미측정 '문맥: BTT-RULE > 05 운전 조건·모터 구동부 룰\n\n05 운전 '
  5. `BTT-MANUAL:2.0:0008` relevance=미측정 '문맥: BTT-MANUAL > 04 기동·속도·DC 입력전류 대응\n\n04'
- **q13** hybrid 정답 2위
  1. `BTT-MANUAL:2.0:0012` relevance=미측정 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  2. `BTT-MANUAL:2.0:0007` relevance=미측정 '문맥: BTT-MANUAL > 04 기동·속도·DC 입력전류 대응\n\n04'
  3. `BTT-RULE:2.0:0007` relevance=미측정 '문맥: BTT-RULE > 05 운전 조건·모터 구동부 룰\n\n05 운전 '
  4. `BTT-MANUAL:2.0:0008` relevance=미측정 '문맥: BTT-MANUAL > 04 기동·속도·DC 입력전류 대응\n\n04'
  5. `BTT-RULE:2.0:0013` relevance=미측정 '문맥: BTT-RULE > 08 진동·측면 변화·복합 판단\n\n08 진동·'
- **q13** reranked 정답 4위
  1. `BTT-SOP-001:1.1:0009` relevance=0.0905 '문맥: BTT-SOP-001 > 제3장 점검·조치 및 재가동\n\n제8조(점'
  2. `BTT-MANUAL:2.0:0004` relevance=0.0332 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP01 '
  3. `BTT-MANUAL:2.0:0006` relevance=0.0276 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP02 '
  4. `BTT-MANUAL:2.0:0007` relevance=0.0257 '문맥: BTT-MANUAL > 04 기동·속도·DC 입력전류 대응\n\n04'
- **q14** dense 정답 3위
  1. `BTT-MANUAL:2.0:0007` relevance=미측정 '문맥: BTT-MANUAL > 04 기동·속도·DC 입력전류 대응\n\n04'
  2. `BTT-SOP-001:1.1:0009` relevance=미측정 '문맥: BTT-SOP-001 > 제3장 점검·조치 및 재가동\n\n제8조(점'
  3. `BTT-MANUAL:2.0:0012` relevance=미측정 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  4. `BTT-SOP-001:1.1:0019` relevance=미측정 '문맥: BTT-SOP-001 > 제5장 설비 방호 및 유지관리\n\n제15조'
  5. `BTT-SOP-001:1.1:0004` relevance=미측정 '문맥: BTT-SOP-001 > 제1장 총칙\n\n제4조(센서 관측의 한계)'
- **q14** hybrid 정답 1위
  1. `BTT-MANUAL:2.0:0012` relevance=미측정 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  2. `BTT-SOP-001:1.1:0009` relevance=미측정 '문맥: BTT-SOP-001 > 제3장 점검·조치 및 재가동\n\n제8조(점'
  3. `BTT-RULE:2.0:0014` relevance=미측정 '문맥: BTT-RULE > 08 진동·측면 변화·복합 판단\n\n08 진동·'
  4. `BTT-RULE:2.0:0013` relevance=미측정 '문맥: BTT-RULE > 08 진동·측면 변화·복합 판단\n\n08 진동·'
  5. `BTT-RULE:2.0:0001` relevance=미측정 '문맥: BTT-RULE > 01 적용 범위와 판정 원칙\n\n01 적용 범위'
- **q14** reranked 정답 2위
  1. `BTT-RULE:2.0:0013` relevance=0.2175 '문맥: BTT-RULE > 08 진동·측면 변화·복합 판단\n\n08 진동·'
  2. `BTT-MANUAL:2.0:0012` relevance=0.1307 '문맥: BTT-MANUAL > 06 진동·충격·특정 측 변화 대응\n\n06'
  3. `BTT-RULE:2.0:0001` relevance=0.0645 '문맥: BTT-RULE > 01 적용 범위와 판정 원칙\n\n01 적용 범위'
  4. `BTT-MANUAL:2.0:0025` relevance=0.0491 '문맥: BTT-MANUAL > 13 정비 후 검증·이력 연결\n\n13 정비'
  5. `BTT-SOP-001:1.1:0009` relevance=0.0461 '문맥: BTT-SOP-001 > 제3장 점검·조치 및 재가동\n\n제8조(점'
- **q15** dense 정답 없음
  1. `BTT-SOP-001:1.1:0004` relevance=미측정 '문맥: BTT-SOP-001 > 제1장 총칙\n\n제4조(센서 관측의 한계)'
  2. `BTT-SOP-001:1.1:0015` relevance=미측정 '문맥: BTT-SOP-001 > 제4장 업무 상태·데이터 및 보안\n\n제1'
  3. `BTT-SOP-001:1.1:0009` relevance=미측정 '문맥: BTT-SOP-001 > 제3장 점검·조치 및 재가동\n\n제8조(점'
  4. `BTT-RULE:2.0:0006` relevance=미측정 '문맥: BTT-RULE > 04 수치 룰 임계값 원장\n\n04 수치 룰 임'
  5. `BTT-RULE:2.0:0001` relevance=미측정 '문맥: BTT-RULE > 01 적용 범위와 판정 원칙\n\n01 적용 범위'
- **q15** hybrid 정답 5위
  1. `BTT-RULE:2.0:0001` relevance=미측정 '문맥: BTT-RULE > 01 적용 범위와 판정 원칙\n\n01 적용 범위'
  2. `BTT-RULE:2.0:0015` relevance=미측정 '문맥: BTT-RULE > 09 데이터 품질·실제 CSV 확인 결과\n\n0'
  3. `BTT-RULE:2.0:0000` relevance=미측정 '문맥: BTT-RULE\n\n| BATTERY TRAY TRANSFER / '
  4. `BTT-SOP-001:1.1:0004` relevance=미측정 '문맥: BTT-SOP-001 > 제1장 총칙\n\n제4조(센서 관측의 한계)'
  5. `BTT-MANUAL:2.0:0013` relevance=미측정 '문맥: BTT-MANUAL > 07 데이터 품질 코드 대응\n\n07 데이터'
- **q15** reranked 정답 1위
  1. `BTT-MANUAL:2.0:0013` relevance=0.6791 '문맥: BTT-MANUAL > 07 데이터 품질 코드 대응\n\n07 데이터'
  2. `BTT-SOP-001:1.1:0009` relevance=0.1969 '문맥: BTT-SOP-001 > 제3장 점검·조치 및 재가동\n\n제8조(점'
  3. `BTT-RULE:2.0:0015` relevance=0.0754 '문맥: BTT-RULE > 09 데이터 품질·실제 CSV 확인 결과\n\n0'
  4. `BTT-RULE:2.0:0001` relevance=0.0257 '문맥: BTT-RULE > 01 적용 범위와 판정 원칙\n\n01 적용 범위'
  5. `BTT-RULE:2.0:0003` relevance=0.0253 '문맥: BTT-RULE > 02 15컬럼 데이터 계약\n\n02 15컬럼 데'
- **q16** dense 정답 2위
  1. `BTT-SOP-001:1.1:0007` relevance=미측정 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제7'
  2. `BTT-SOP-001:1.1:0008` relevance=미측정 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제7'
  3. `BTT-SOP-001:1.1:0006` relevance=미측정 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제6'
  4. `BTT-SOP-001:1.1:0027` relevance=미측정 '문맥: BTT-SOP-001 > 제7장 RAG 등록 및 해석\n\n별지 제1'
  5. `BTT-SOP-001:1.1:0009` relevance=미측정 '문맥: BTT-SOP-001 > 제3장 점검·조치 및 재가동\n\n제8조(점'
- **q16** hybrid 정답 2위
  1. `BTT-SOP-001:1.1:0007` relevance=미측정 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제7'
  2. `BTT-SOP-001:1.1:0008` relevance=미측정 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제7'
  3. `BTT-SOP-001:1.1:0027` relevance=미측정 '문맥: BTT-SOP-001 > 제7장 RAG 등록 및 해석\n\n별지 제1'
  4. `BTT-SOP-001:1.1:0006` relevance=미측정 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제6'
  5. `BTT-SOP-001:1.1:0005` relevance=미측정 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제5'
- **q16** reranked 정답 3위
  1. `BTT-SOP-001:1.1:0007` relevance=0.9775 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제7'
  2. `BTT-SOP-001:1.1:0027` relevance=0.9740 '문맥: BTT-SOP-001 > 제7장 RAG 등록 및 해석\n\n별지 제1'
  3. `BTT-SOP-001:1.1:0008` relevance=0.9563 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제7'
  4. `BTT-SOP-001:1.1:0003` relevance=0.8268 '문맥: BTT-SOP-001 > 제1장 총칙\n\n제3조(역할과 권한)\n\n①'
  5. `BTT-MANUAL:2.0:0025` relevance=0.6965 '문맥: BTT-MANUAL > 13 정비 후 검증·이력 연결\n\n13 정비'
- **q17** dense 정답 1위
  1. `BTT-SOP-001:1.1:0006` relevance=미측정 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제6'
  2. `BTT-RULE:2.0:0007` relevance=미측정 '문맥: BTT-RULE > 05 운전 조건·모터 구동부 룰\n\n05 운전 '
  3. `BTT-MANUAL:2.0:0007` relevance=미측정 '문맥: BTT-MANUAL > 04 기동·속도·DC 입력전류 대응\n\n04'
  4. `BTT-SOP-001:1.1:0005` relevance=미측정 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제5'
  5. `BTT-MANUAL:2.0:0001` relevance=미측정 '문맥: BTT-MANUAL > 01 공통 대응·역할·우선순위\n\n01 공통'
- **q17** hybrid 정답 1위
  1. `BTT-SOP-001:1.1:0006` relevance=미측정 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제6'
  2. `BTT-RULE:2.0:0007` relevance=미측정 '문맥: BTT-RULE > 05 운전 조건·모터 구동부 룰\n\n05 운전 '
  3. `BTT-MANUAL:2.0:0001` relevance=미측정 '문맥: BTT-MANUAL > 01 공통 대응·역할·우선순위\n\n01 공통'
  4. `BTT-SOP-001:1.1:0005` relevance=미측정 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제5'
  5. `BTT-SOP-001:1.1:0010` relevance=미측정 '문맥: BTT-SOP-001 > 제3장 점검·조치 및 재가동\n\n제9조(일'
- **q17** reranked 정답 1위
  1. `BTT-SOP-001:1.1:0006` relevance=0.9596 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제6'
  2. `BTT-MANUAL:2.0:0025` relevance=0.2838 '문맥: BTT-MANUAL > 13 정비 후 검증·이력 연결\n\n13 정비'
  3. `BTT-RULE:2.0:0017` relevance=0.0576 '문맥: BTT-RULE > 10 구현·인수시험·변경 관리\n\n10 구현·인'
  4. `BTT-MANUAL:2.0:0001` relevance=0.0439 '문맥: BTT-MANUAL > 01 공통 대응·역할·우선순위\n\n01 공통'
  5. `BTT-RULE:2.0:0007` relevance=0.0292 '문맥: BTT-RULE > 05 운전 조건·모터 구동부 룰\n\n05 운전 '
- **q18** dense 정답 3위
  1. `BTT-SOP-001:1.1:0016` relevance=미측정 '문맥: BTT-SOP-001 > 제4장 업무 상태·데이터 및 보안\n\n제1'
  2. `BTT-SOP-001:1.1:0012` relevance=미측정 '문맥: BTT-SOP-001 > 제3장 점검·조치 및 재가동\n\n제10조('
  3. `BTT-SOP-001:1.1:0003` relevance=미측정 '문맥: BTT-SOP-001 > 제1장 총칙\n\n제3조(역할과 권한)\n\n①'
  4. `BTT-SOP-001:1.1:0011` relevance=미측정 '문맥: BTT-SOP-001 > 제3장 점검·조치 및 재가동\n\n제10조('
  5. `BTT-SOP-001:1.1:0013` relevance=미측정 '문맥: BTT-SOP-001 > 제4장 업무 상태·데이터 및 보안\n\n제1'
- **q18** hybrid 정답 1위
  1. `BTT-SOP-001:1.1:0003` relevance=미측정 '문맥: BTT-SOP-001 > 제1장 총칙\n\n제3조(역할과 권한)\n\n①'
  2. `BTT-SOP-001:1.1:0012` relevance=미측정 '문맥: BTT-SOP-001 > 제3장 점검·조치 및 재가동\n\n제10조('
  3. `BTT-SOP-001:1.1:0016` relevance=미측정 '문맥: BTT-SOP-001 > 제4장 업무 상태·데이터 및 보안\n\n제1'
  4. `BTT-MANUAL:2.0:0026` relevance=미측정 '문맥: BTT-MANUAL > 13 정비 후 검증·이력 연결\n\n13 정비'
  5. `BTT-SOP-001:1.1:0013` relevance=미측정 '문맥: BTT-SOP-001 > 제4장 업무 상태·데이터 및 보안\n\n제1'
- **q18** reranked 정답 1위
  1. `BTT-SOP-001:1.1:0003` relevance=0.6097 '문맥: BTT-SOP-001 > 제1장 총칙\n\n제3조(역할과 권한)\n\n①'
  2. `BTT-SOP-001:1.1:0016` relevance=0.4193 '문맥: BTT-SOP-001 > 제4장 업무 상태·데이터 및 보안\n\n제1'
  3. `BTT-SOP-001:1.1:0028` relevance=0.4030 '문맥: BTT-SOP-001 > 제7장 RAG 등록 및 해석\n\n별지 제2'
  4. `BTT-SOP-001:1.1:0022` relevance=0.2818 '문맥: BTT-SOP-001 > 제6장 인계·교육 및 기록 관리\n\n제18'
  5. `BTT-SOP-001:1.1:0013` relevance=0.1489 '문맥: BTT-SOP-001 > 제4장 업무 상태·데이터 및 보안\n\n제1'
- **o01** dense 근거 오반환
  1. `BTT-MANUAL:2.0:0024` relevance=미측정 '문맥: BTT-MANUAL > 12 기계 원인별 추가 점검\n\n12 기계 '
  2. `BTT-MANUAL:2.0:0023` relevance=미측정 '문맥: BTT-MANUAL > 12 기계 원인별 추가 점검\n\n12 기계 '
  3. `BTT-MANUAL:2.0:0006` relevance=미측정 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP02 '
  4. `BTT-RULE:2.0:0001` relevance=미측정 '문맥: BTT-RULE > 01 적용 범위와 판정 원칙\n\n01 적용 범위'
  5. `BTT-MANUAL:2.0:0025` relevance=미측정 '문맥: BTT-MANUAL > 13 정비 후 검증·이력 연결\n\n13 정비'
- **o01** hybrid 근거 오반환
  1. `BTT-MANUAL:2.0:0024` relevance=미측정 '문맥: BTT-MANUAL > 12 기계 원인별 추가 점검\n\n12 기계 '
  2. `BTT-SOP-001:1.1:0019` relevance=미측정 '문맥: BTT-SOP-001 > 제5장 설비 방호 및 유지관리\n\n제15조'
  3. `BTT-RULE:2.0:0001` relevance=미측정 '문맥: BTT-RULE > 01 적용 범위와 판정 원칙\n\n01 적용 범위'
  4. `BTT-MANUAL:2.0:0006` relevance=미측정 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP02 '
  5. `BTT-MANUAL:2.0:0023` relevance=미측정 '문맥: BTT-MANUAL > 12 기계 원인별 추가 점검\n\n12 기계 '
- **o01** reranked 근거 없음 거절 성공
- **o02** dense 근거 오반환
  1. `BTT-MANUAL:2.0:0000` relevance=미측정 '문맥: BTT-MANUAL\n\n| BATTERY TRAY TRANSFER '
  2. `BTT-SOP-001:1.1:0007` relevance=미측정 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제7'
  3. `BTT-SOP-001:1.1:0000` relevance=미측정 '문맥: BTT-SOP-001\n\n| BATTERY TRAY TRANSFER'
  4. `BTT-SOP-001:1.1:0009` relevance=미측정 '문맥: BTT-SOP-001 > 제3장 점검·조치 및 재가동\n\n제8조(점'
  5. `BTT-SOP-001:1.1:0032` relevance=미측정 '문맥: BTT-SOP-001 > 제7장 RAG 등록 및 해석\n\n참고 부록'
- **o02** hybrid 근거 오반환
  1. `BTT-SOP-001:1.1:0009` relevance=미측정 '문맥: BTT-SOP-001 > 제3장 점검·조치 및 재가동\n\n제8조(점'
  2. `BTT-MANUAL:2.0:0000` relevance=미측정 '문맥: BTT-MANUAL\n\n| BATTERY TRAY TRANSFER '
  3. `BTT-SOP-001:1.1:0032` relevance=미측정 '문맥: BTT-SOP-001 > 제7장 RAG 등록 및 해석\n\n참고 부록'
  4. `BTT-SOP-001:1.1:0000` relevance=미측정 '문맥: BTT-SOP-001\n\n| BATTERY TRAY TRANSFER'
  5. `BTT-MANUAL:2.0:0018` relevance=미측정 '문맥: BTT-MANUAL > 09 실제 제조사 알람과 내부 코드 구분\n'
- **o02** reranked 근거 오반환
  1. `BTT-SOP-001:1.1:0009` relevance=0.3736 '문맥: BTT-SOP-001 > 제3장 점검·조치 및 재가동\n\n제8조(점'
  2. `BTT-SOP-001:1.1:0029` relevance=0.0239 '문맥: BTT-SOP-001 > 제7장 RAG 등록 및 해석\n\n별지 제3'
- **o03** dense 근거 오반환
  1. `BTT-MANUAL:2.0:0024` relevance=미측정 '문맥: BTT-MANUAL > 12 기계 원인별 추가 점검\n\n12 기계 '
  2. `BTT-MANUAL:2.0:0000` relevance=미측정 '문맥: BTT-MANUAL\n\n| BATTERY TRAY TRANSFER '
  3. `BTT-RULE:2.0:0000` relevance=미측정 '문맥: BTT-RULE\n\n| BATTERY TRAY TRANSFER / '
  4. `BTT-SOP-001:1.1:0000` relevance=미측정 '문맥: BTT-SOP-001\n\n| BATTERY TRAY TRANSFER'
  5. `BTT-SOP-001:1.1:0020` relevance=미측정 '문맥: BTT-SOP-001 > 제5장 설비 방호 및 유지관리\n\n제16조'
- **o03** hybrid 근거 오반환
  1. `BTT-MANUAL:2.0:0005` relevance=미측정 '문맥: BTT-MANUAL > 03 이송·광전 현장 대응 절차\n\nP03 '
  2. `BTT-SOP-001:1.1:0007` relevance=미측정 '문맥: BTT-SOP-001 > 제2장 이상 대응 및 에너지 격리\n\n제7'
  3. `BTT-MANUAL:2.0:0024` relevance=미측정 '문맥: BTT-MANUAL > 12 기계 원인별 추가 점검\n\n12 기계 '
  4. `BTT-MANUAL:2.0:0000` relevance=미측정 '문맥: BTT-MANUAL\n\n| BATTERY TRAY TRANSFER '
  5. `BTT-RULE:2.0:0006` relevance=미측정 '문맥: BTT-RULE > 04 수치 룰 임계값 원장\n\n04 수치 룰 임'
- **o03** reranked 근거 없음 거절 성공
- **o04** dense 근거 오반환
  1. `BTT-RULE:2.0:0003` relevance=미측정 '문맥: BTT-RULE > 02 15컬럼 데이터 계약\n\n02 15컬럼 데'
  2. `BTT-RULE:2.0:0004` relevance=미측정 '문맥: BTT-RULE > 03 등급·지속시간·회복 조건\n\n03 등급·지'
  3. `BTT-RULE:2.0:0012` relevance=미측정 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
  4. `BTT-RULE:2.0:0002` relevance=미측정 '문맥: BTT-RULE > 02 15컬럼 데이터 계약\n\n02 15컬럼 데'
  5. `BTT-RULE:2.0:0011` relevance=미측정 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
- **o04** hybrid 근거 오반환
  1. `BTT-RULE:2.0:0003` relevance=미측정 '문맥: BTT-RULE > 02 15컬럼 데이터 계약\n\n02 15컬럼 데'
  2. `BTT-RULE:2.0:0004` relevance=미측정 '문맥: BTT-RULE > 03 등급·지속시간·회복 조건\n\n03 등급·지'
  3. `BTT-RULE:2.0:0012` relevance=미측정 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
  4. `BTT-RULE:2.0:0002` relevance=미측정 '문맥: BTT-RULE > 02 15컬럼 데이터 계약\n\n02 15컬럼 데'
  5. `BTT-RULE:2.0:0011` relevance=미측정 '문맥: BTT-RULE > 07 이송 이상 룰·시간 기준\n\n07 이송 이'
- **o04** reranked 근거 없음 거절 성공
- **o05** dense 근거 오반환
  1. `BTT-MANUAL:2.0:0010` relevance=미측정 '문맥: BTT-MANUAL > 05 공급전압·외함 온도 대응\n\n05 공급'
  2. `BTT-MANUAL:2.0:0009` relevance=미측정 '문맥: BTT-MANUAL > 05 공급전압·외함 온도 대응\n\n05 공급'
  3. `BTT-SOP-001:1.1:0031` relevance=미측정 '문맥: BTT-SOP-001 > 제7장 RAG 등록 및 해석\n\n| 근거 '
  4. `BTT-MANUAL:2.0:0019` relevance=미측정 '문맥: BTT-MANUAL > 10 출처·적용 범위\n\n10 출처·적용 범'
  5. `BTT-MANUAL:2.0:0018` relevance=미측정 '문맥: BTT-MANUAL > 09 실제 제조사 알람과 내부 코드 구분\n'
- **o05** hybrid 근거 오반환
  1. `BTT-MANUAL:2.0:0010` relevance=미측정 '문맥: BTT-MANUAL > 05 공급전압·외함 온도 대응\n\n05 공급'
  2. `BTT-SOP-001:1.1:0031` relevance=미측정 '문맥: BTT-SOP-001 > 제7장 RAG 등록 및 해석\n\n| 근거 '
  3. `BTT-MANUAL:2.0:0009` relevance=미측정 '문맥: BTT-MANUAL > 05 공급전압·외함 온도 대응\n\n05 공급'
  4. `BTT-RULE:2.0:0008` relevance=미측정 '문맥: BTT-RULE > 05 운전 조건·모터 구동부 룰\n\n05 운전 '
  5. `BTT-MANUAL:2.0:0018` relevance=미측정 '문맥: BTT-MANUAL > 09 실제 제조사 알람과 내부 코드 구분\n'
- **o05** reranked 근거 없음 거절 성공
- **o06** dense 근거 오반환
  1. `BTT-RULE:2.0:0000` relevance=미측정 '문맥: BTT-RULE\n\n| BATTERY TRAY TRANSFER / '
  2. `BTT-MANUAL:2.0:0000` relevance=미측정 '문맥: BTT-MANUAL\n\n| BATTERY TRAY TRANSFER '
  3. `BTT-RULE:2.0:0020` relevance=미측정 '문맥: BTT-RULE > 11 근거·데이터 출처\n\n11 근거·데이터 출'
  4. `BTT-MANUAL:2.0:0008` relevance=미측정 '문맥: BTT-MANUAL > 04 기동·속도·DC 입력전류 대응\n\n04'
  5. `BTT-MANUAL:2.0:0010` relevance=미측정 '문맥: BTT-MANUAL > 05 공급전압·외함 온도 대응\n\n05 공급'
- **o06** hybrid 근거 오반환
  1. `BTT-MANUAL:2.0:0000` relevance=미측정 '문맥: BTT-MANUAL\n\n| BATTERY TRAY TRANSFER '
  2. `BTT-SOP-001:1.1:0002` relevance=미측정 '문맥: BTT-SOP-001 > 제1장 총칙\n\n제2조(적용 범위 및 적용'
  3. `BTT-MANUAL:2.0:0010` relevance=미측정 '문맥: BTT-MANUAL > 05 공급전압·외함 온도 대응\n\n05 공급'
  4. `BTT-MANUAL:2.0:0009` relevance=미측정 '문맥: BTT-MANUAL > 05 공급전압·외함 온도 대응\n\n05 공급'
  5. `BTT-RULE:2.0:0000` relevance=미측정 '문맥: BTT-RULE\n\n| BATTERY TRAY TRANSFER / '
- **o06** reranked 근거 없음 거절 성공

## 실행 설정

- 청킹 방식: `structured`
- 질의 파일: `data\eval\rag_queries_v1.toml` (36개)
- 임베딩: `BAAI/bge-m3`
- 리랭커: `BAAI/bge-reranker-v2-m3`
- 리랭커 추론 배치 크기: 2
- 후보 수: 30, 최종 k: 5
- 관련도 하한: 0.02
- 실행 중 임베딩 캐시: 사용
- 질의 임베딩 사전 계산 후 모델 해제: 사용
- 처리 시간은 위 캐시 설정을 포함한다. 캐시 사용 결과는 순수 추론 속도가 아니다.
