"""22개 코드별 정비 사례 15건씩 등록한다. 모델·센서 실측을 실행하지 않는다."""

import argparse
from urllib.parse import urlsplit

from report_case_variants import MORE_VARIANTS, VARIANTS
from seed_22_reports import CASES, index_cases, seed_cases

from weeing_weeing.config import get_settings
from weeing_weeing.db import interface as db
from weeing_weeing.rag import interface as rag

RECOVERY = {
    "P01": ("시험 트레이 이송시간", (14.7, 15.0, 15.3), "초"),
    "P02": ("시험 트레이 이송시간", (14.6, 15.1, 15.4), "초"),
    "P03": ("입구 센서 해제 유지 시간", (2.5, 3.0, 3.5), "초"),
    "P04": ("출구 센서 해제 유지 시간", (2.6, 3.1, 3.6), "초"),
    "P05": ("시험 투입 간격", (4.8, 5.0, 5.2), "초"),
    "P06": ("시험 트레이 이송시간", (14.8, 15.1, 15.4), "초"),
    "P07": ("시험 트레이 이송시간 중앙값", (14.8, 15.0, 15.2), "초"),
    "M02": ("회복 후 모터 속도", (1010, 1015, 1020), "rpm"),
    "M03": ("회복 후 모터 속도", (1010, 1015, 1020), "rpm"),
    "M05": ("회복 후 DC 입력전류", (0.091, 0.092, 0.093), "A"),
    "M06": ("회복 후 DC 입력전류", (0.091, 0.092, 0.093), "A"),
    "M07": ("회복 후 DC 버스전압", (23.8, 24.0, 24.2), "V"),
    "M08": ("회복 후 DC 버스전압", (23.8, 24.0, 24.2), "V"),
    "M10": ("회복 후 모터 외함 온도", (67, 69, 71), "℃"),
    "M11": ("회복 후 구동측 진동 RMS", (0.052, 0.060, 0.068), "g"),
    "M12": ("회복 후 구동측 진동 RMS", (0.052, 0.060, 0.068), "g"),
    "M13": ("회복 후 구동측 첨도", (4.1, 4.8, 5.4), ""),
    "M14": ("회복 후 구동측 첨도", (4.1, 4.8, 5.4), ""),
    "M15": ("회복 후 반구동측 진동 RMS", (0.052, 0.055, 0.059), "g"),
    "M16": ("회복 후 반구동측 진동 RMS", (0.052, 0.055, 0.059), "g"),
    "M17": ("회복 후 반구동측 첨도", (3.8, 4.2, 4.8), ""),
    "M18": ("회복 후 반구동측 첨도", (3.8, 4.2, 4.8), ""),
}


def build_entries():
    expected = {case[0] for case in CASES}
    if (
        len(CASES) != 22
        or set(VARIANTS) != expected
        or set(MORE_VARIANTS) != expected
        or set(RECOVERY) != expected
    ):
        raise ValueError("22개 코드의 사례 구성이 올바르지 않습니다.")
    entries = []
    for base in CASES:
        code, field, value, unit, threshold, cause, action, trial = base
        alternatives = VARIANTS[code]
        if len(alternatives) != 2 or len(MORE_VARIANTS[code]) != 2:
            raise ValueError(f"{code}의 추가 원인 유형은 네 개여야 합니다.")
        types = [(cause, action, trial), *alternatives, *MORE_VARIANTS[code]]
        for type_index, (new_cause, new_action, new_trial) in enumerate(types):
            for repeat in range(3):
                sequence = type_index * 3 + repeat + 1
                label, readings, unit_label = RECOVERY[code]
                trial_text = (
                    new_trial
                    if sequence == 1
                    else f"{new_trial} {label}: {readings[repeat]}{unit_label}."
                )
                entries.append(
                    (
                        (
                            code,
                            field,
                            value,
                            unit,
                            threshold,
                            new_cause,
                            new_action,
                            trial_text,
                        ),
                        sequence,
                    )
                )
    return entries


def validate_target(settings, aws):
    """AWS 모드는 배포 compose의 postgres/qdrant 서비스만 허용한다."""
    db_host = urlsplit(settings.database_url).hostname
    qdrant_host = (
        urlsplit(settings.qdrant_url).hostname if settings.qdrant_url else None
    )
    if aws:
        if (
            db_host != "postgres"
            or settings.vector_store != "qdrant"
            or qdrant_host != "qdrant"
        ):
            raise ValueError(
                "AWS 모드는 Docker의 postgres 및 qdrant 서비스만 허용합니다."
            )
    elif db_host not in ("localhost", "127.0.0.1", "::1") or (
        settings.vector_store == "qdrant"
        and qdrant_host not in ("localhost", "127.0.0.1", "::1")
    ):
        raise ValueError("로컬 PostgreSQL과 로컬 Qdrant 서버가 필요합니다.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--author", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--approver", required=True)
    parser.add_argument(
        "--aws", action="store_true", help="AWS Docker 내부 서비스에 등록"
    )
    args = parser.parse_args()
    settings = get_settings()
    validate_target(settings, args.aws)
    incidents, reports, users = (
        db.open_incidents(settings.database_url),
        db.open_reports(settings.database_url),
        db.open_users(settings.database_url),
    )
    try:
        results = seed_cases(
            incidents,
            reports,
            users,
            args.author,
            args.reviewer,
            args.approver,
            entries=build_entries(),
        )
        print(
            f"보고서 {len(results)}건 확인: 신규 {sum(row[2] == '생성' for row in results)}건, 기존 {sum(row[2] == '기존' for row in results)}건"
        )
        indexed, failed = index_cases(reports, results, rag.get_indexer)
        print(
            f"검색 등록 완료 {indexed}건, 실패 {failed}건 (이미 등록된 사례는 건너뜀)"
        )
        if failed:
            raise SystemExit(
                "검색 등록 실패. 원인을 확인하고 같은 명령을 다시 실행하세요."
            )
    finally:
        rag.close_rag_resources()
        for repo in (incidents, reports, users):
            repo._engine.dispose()


if __name__ == "__main__":
    main()
