"""22개 코드별 정비 사례 15건씩 등록한다. 모델·센서 실측을 실행하지 않는다."""

import argparse
from urllib.parse import urlsplit

from report_case_variants import VARIANTS
from seed_22_reports import CASES, index_cases, seed_cases

from weeing_weeing.config import get_settings
from weeing_weeing.db import interface as db
from weeing_weeing.rag import interface as rag

# 각 원인 유형의 점검 기록은 서로 유사할 수 있으며 측정값을 임의로 추가하지 않는다.
TRIAL_NOTES = (
    "점검 후 관련 센서 표시와 설비 동작을 대조했다.",
    "조치 전후 센서 표시와 운전 상태를 비교했다.",
    "시험 과정에서 동일 이상이 재발하는지 확인했다.",
    "동일한 운전 조건에서 설비 동작을 다시 확인했다.",
    "관측값과 실제 설비 상태가 일치하는지 확인했다.",
)


def build_entries():
    expected = {case[0] for case in CASES}
    if len(CASES) != 22 or set(VARIANTS) != expected:
        raise ValueError("22개 코드의 사례 구성이 올바르지 않습니다.")
    entries = []
    for base in CASES:
        code, field, value, unit, threshold, cause, action, trial = base
        alternatives = VARIANTS[code]
        if len(alternatives) != 2:
            raise ValueError(f"{code}의 추가 원인 유형은 두 개여야 합니다.")
        types = [(cause, action, trial), *alternatives]
        for type_index, (new_cause, new_action, new_trial) in enumerate(types):
            for repeat in range(5):
                sequence = type_index * 5 + repeat + 1
                trial_text = (
                    new_trial if sequence == 1 else f"{new_trial} {TRIAL_NOTES[repeat]}"
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
