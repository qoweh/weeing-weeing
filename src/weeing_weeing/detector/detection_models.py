"""
센서 탐지의 설정·운전 문맥·내부 추적 상태를 정의한다.

탐지 동작은 anomaly_detector.py에, 반환되는 이상 관측은 observation.py에 둔다.
이 파일은 detector 내부에서 공유하며 다른 모듈의 구현을 참조하지 않는다.
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite

from weeing_weeing.contracts import TelemetryRecord


@dataclass(frozen=True)
class NumericRange:
    """수치 센서 하나의 정상 구간과 단위를 담는 설정값.

    lower <= 센서값 <= upper이면 정상이다. 범위 밖이면 이상 관측을 만든다.
    frozen=True이므로 생성 후 속성을 바꿀 수 없고, 변경 시 새 객체를 만든다.
    Warning/Error 등급별 경계가 아니라 A 정상 범위만 표현한다.
    """

    lower: float  # 정상 하한. 이 값과 같으면 정상이며, 더 작으면 범위 이탈이다.
    upper: float  # 정상 상한. 이 값과 같으면 정상이며, 더 크면 범위 이탈이다.
    unit: str  # 센서값 단위. 예: rpm, A, V, ℃, g. 무차원 첨도는 "-".

    def __post_init__(self) -> None:
        """생성 직후 NaN·무한대 또는 뒤집힌 범위를 거부한다."""
        if not all(isfinite(value) for value in (self.lower, self.upper)):
            raise ValueError("정상 범위에는 유한한 수치가 필요함")
        if self.lower > self.upper:
            raise ValueError("정상 범위의 하한은 상한보다 클 수 없음")


# BTT-RULE v2.0 4절의 A 정상 범위. B/C 등급 구분은 사건 판단 단계에서 한다.
DEFAULT_NUMERIC_RANGES = {
    "rpm": NumericRange(1000, 1030, "rpm"),
    "dc_input_current_a": NumericRange(0.089963, 0.093786, "A"),
    "dc_bus_voltage_v": NumericRange(20, 25, "V"),
    "motor_housing_temp_c": NumericRange(45, 85, "℃"),
    "de_vibration_rms_g": NumericRange(0.040396, 0.080601, "g"),
    "de_kurtosis": NumericRange(3.5511, 7.0661, "-"),
    "nde_vibration_rms_g": NumericRange(0.049179, 0.062322, "g"),
    "nde_kurtosis": NumericRange(3.3565, 5.4770, "-"),
}


@dataclass(frozen=True)
class DetectionContext:
    """호출자가 매 레코드와 함께 전달하는 운전 상황의 스냅샷.

    센서 CSV에 없는 PLC·시뮬레이터 정보를 담으며, 탐지 이력을 저장하지 않는다.
    선택형 bool의 None은 정보 미확보다. True 또는 False로 추정하지 않는다.
    현재 구현에서는 광전·시간 검사에 적용하며 수치 범위 검사는 별도로 수행한다.
    후속 공정은 항상 수신 가능하다고 가정하므로 수신 가능 여부는 입력받지 않는다.
    운전 중에는 항상 5초 주기로 투입된다고 가정하며, 허용오차는 탐지기 설정을 따른다.
    """

    # 운전 지령. True일 때 투입 간격·FIFO 이송을 검사한다. False/None이면 해당 검사를 건너뛰고 FIFO와 상승 엣지 추적을 초기화한다.
    run_cmd: bool | None = None


@dataclass
class _Tray:
    """입구 상승 엣지 하나에 대응하는 FIFO 내부의 가상 트레이.

    실제 트레이 ID가 아니라 입구 이벤트로 만든 추적 대상이다.
    진입 순서대로 반드시 나온다고 가정하며, 지연 중에도 출구와 대응할 때까지 큐에 남긴다.
    이름 앞의 _는 detector 내부에서만 사용하는 타입이라는 의미다.
    """

    seq: int  # 해당 공정·설비의 추적 상태 안에서 부여한 가상 트레이 순번.
    entered_at: datetime  # 입구 False → True가 관측된 레코드의 timestamp.


@dataclass
class _SensorState:
    """AnomalyDetector가 공정·설비별로 유지하고 매 레코드마다 갱신하는 상태.

    (process_id, asset_id)마다 별도 객체를 두어 다른 설비의 이력이 섞이지 않는다.
    센서 엣지·경과시간·FIFO 계산용이며 Incident 생성·회복·종결을 관리하지 않는다.
    dict·deque는 default_factory로 만들어 인스턴스 사이에서 공유하지 않는다.
    """

    # 마지막으로 처리한 입력. 엣지, 중복 입력, 시간 역행·공백을 확인하는 기준.
    # 최초 관측 또는 추적 초기화 직후에는 None이다.
    previous: TelemetryRecord | None = None

    # 센서 필드명 → 현재 연속 True 구간의 관측 시작 시각.
    # False가 되면 해당 키를 제거한다.
    occupied_since: dict[str, datetime] = field(default_factory=dict)

    # 센서 필드명 → 마지막 False → True 시각. 투입 간격·출구 무이벤트 계산에 사용.
    last_rising: dict[str, datetime] = field(default_factory=dict)

    # 센서 필드명 → 마지막 True → False 시각. 현재는 엣지 이력을 보관하며, 이 값 자체를 이용한 별도의 이상 판정은 수행하지 않는다.
    last_falling: dict[str, datetime] = field(default_factory=dict)

    # 입구에서 관측됐지만 출구와 아직 대응하지 않은 트레이의 FIFO 큐.
    # 왼쪽이 가장 오래된 진입이며, 시간 초과 트레이도 유지한다.
    pending: deque[_Tray] = field(default_factory=deque)

    next_tray_seq: int = 1  # 다음 입구 상승 엣지에 부여할 순번. 등록 후 1 증가한다.
