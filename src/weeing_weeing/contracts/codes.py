"""룰 코드와 판정 등급 (BTT-RULE v2.0).

출처: 룰베이스 최종 정의서 v2.0 3·4·5·7·8·9절. 코드는 제조사 알람이 아니라
이 프로젝트의 관측 코드다. 임계값·지속시간은 detector/plc 모듈 설정에서 관리한다.
"""

from enum import StrEnum
from typing import Literal

RULE_VERSION = "BTT-RULE 2.0"
CODE_PREFIX = "BTT2-"


class Severity(StrEnum):
    """판정 등급 (정의서 3절). 하한/상한 방향은 Direction으로 따로 둔다."""

    NORMAL = "Normal"
    WARNING = "Warning"
    ERROR = "Error"
    UNKNOWN = "Unknown"  # 입력·문맥 부족으로 판정 불가
    SUPPRESSED = "Suppressed"  # 계획 정지·대기·정비 등 승인된 평가 억제


# 수치 룰의 이탈 방향. L = 하한(B 쪽), H = 상한(C 쪽)
Direction = Literal["L", "H"]

# 코드 → 표시명. P: 이송·광전, M: 모터 구동부·진동, D: 데이터 품질
CODES: dict[str, str] = {
    "BTT2-P01": "이송시간 초과",
    "BTT2-P02": "빠른 이송",
    "BTT2-P03": "입구 장기 점유",
    "BTT2-P04": "출구 장기 점유",
    "BTT2-P05": "투입 주기 이탈",
    "BTT2-P06": "출구 이벤트 없음",
    "BTT2-P07": "이송시간 증가·불안정",
    "BTT2-M01": "기동 미도달·운전 중 정지",
    "BTT2-M02": "RPM 하한 이탈",
    "BTT2-M03": "RPM 상한 이탈",
    "BTT2-M04": "RPM 변동",
    "BTT2-M05": "DC 입력전류 하한 이탈",
    "BTT2-M06": "DC 입력전류 상한 이탈",
    "BTT2-M07": "DC 버스전압 하한 이탈",
    "BTT2-M08": "DC 버스전압 상한 이탈",
    "BTT2-M09": "외함 온도 하한 이탈",
    "BTT2-M10": "외함 온도 상한 이탈",
    "BTT2-M11": "DE 진동 RMS 하한 이탈",
    "BTT2-M12": "DE 진동 RMS 상한 이탈",
    "BTT2-M13": "DE 첨도 하한 이탈",
    "BTT2-M14": "DE 첨도 상한 이탈",
    "BTT2-M15": "NDE 진동 RMS 하한 이탈",
    "BTT2-M16": "NDE 진동 RMS 상한 이탈",
    "BTT2-M17": "NDE 첨도 하한 이탈",
    "BTT2-M18": "NDE 첨도 상한 이탈",
    "BTT2-M19": "특정 측 진동 상대 변화",
    "BTT2-D01": "형식·식별 오류",
    "BTT2-D02": "필수값 미확보",
    "BTT2-D03": "시간·신선도 오류",
    "BTT2-D04": "추적 신뢰성 부족",
    "BTT2-D05": "설정·문맥 미확보",
}
