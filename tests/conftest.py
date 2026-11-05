import csv
from pathlib import Path

import pytest

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
SAMPLE_CSV = DATA_DIR / "telemetry" / "battery_tray_transfer_telemetry_v3_15cols.csv"


@pytest.fixture
def sample_rows() -> list[dict[str, str]]:
    """Telemetry v3 원본 60행. 첫 컬럼에 BOM이 있어 utf-8-sig로 읽는다."""
    with SAMPLE_CSV.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


@pytest.fixture(autouse=True)
def _fast_password_hash(request, monkeypatch):
    """비밀번호 해시를 테스트용 강도로 낮춘다(운영 2**17은 1회 약 0.3초).

    형식·검증 경로는 같다. 운영 강도 자체는 @pytest.mark.real_scrypt 테스트가 확인한다.
    """
    if request.node.get_closest_marker("real_scrypt"):
        return
    try:
        from weeing_weeing.db import users
    except ImportError:  # dev 그룹만 설치한 검사(make 호환성)에는 DB 의존성이 없다
        return

    monkeypatch.setattr(users, "SCRYPT_N", 2**10)


_PDF_CACHE: dict = {}


@pytest.fixture(autouse=True)
def _reuse_pdf_parse(monkeypatch):
    """같은 PDF·같은 인수의 파싱 결과를 테스트 세션 동안 재사용한다(파싱 1회 약 0.8초).

    parse_pdf는 파일 내용과 인수가 같으면 결과가 같은 결정적 함수다. 첫 호출은 실제로 파싱하고,
    이후에는 깊은 복사본을 돌려줘 테스트끼리 결과를 바꿔도 섞이지 않는다. 파서 자체 테스트는
    pdf_parser.parse_pdf를 직접 불러 이 재사용을 거치지 않는다.
    """
    import copy
    import hashlib
    from pathlib import Path

    try:
        from weeing_weeing.rag import parsers, pdf_parser
    except ImportError:  # dev 그룹만 설치한 검사에는 PDF 의존성이 없다
        return

    real = pdf_parser.parse_pdf

    def cached(pdf_path, **kwargs):
        digest = hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest()
        key = (digest, repr(sorted(kwargs.items())))
        if key not in _PDF_CACHE:
            _PDF_CACHE[key] = real(pdf_path, **kwargs)
        return copy.deepcopy(_PDF_CACHE[key])

    monkeypatch.setattr(parsers, "parse_pdf", cached)
