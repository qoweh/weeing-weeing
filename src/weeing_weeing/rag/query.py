"""Incident → 검색 질의문.

형식: "<짧은 코드> <코드 이름> … 발생 시 원인 점검과 현장 대응 절차"
    예: BTT2-P03 → "P03 입구 장기 점유 발생 시 원인 점검과 현장 대응 절차"

실측(2026-10-27, docs/RAG_E2E.md, 코드 질의 6개, MRR):

    | 형식                               | hybrid | +리랭커 |
    | 전체 코드 + 짧은 코드 + 이름         | 0.422  | 0.458  |
    | 짧은 코드 + 이름                    | 0.514  | 0.639  |
    | 짧은 코드 + 이름 + 대응 문구 (채택)   | 0.833  | 1.000  |

전체 코드(BTT2-P03)와 이름만 넣으면 여러 코드를 나열한 "코드 목록 표" 조각에 끌려간다.
문서의 대응 절은 짧은 코드로 쓰고("P03 / P04 - 센서 장기 점유"), "점검·대응" 같은 말이
대응 절 쪽으로 의미를 당긴다. 표본이 작으므로 평가셋이 커지면 다시 확인한다.

코드 필터(where={"codes": ...})는 기본으로 걸지 않는다. SOP처럼 코드가 없는 조각(정지·격리·
재가동 절차)이 근거에서 빠지기 때문이다.
"""

from weeing_weeing.contracts import CODES, Incident

INTENT = "발생 시 원인 점검과 현장 대응 절차"


def incident_query(incident: Incident) -> str:
    return codes_query(incident.codes)


def codes_query(codes: list[str] | tuple[str, ...]) -> str:
    parts: list[str] = []
    for code in dict.fromkeys(codes):  # 순서 유지, 중복 제거
        parts += [code.split("-", 1)[-1], CODES.get(code, "")]
    return " ".join(p for p in [*parts, INTENT] if p)
