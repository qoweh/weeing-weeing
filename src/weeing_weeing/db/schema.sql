-- 보고서 관리 정보
CREATE TABLE reports (
    report_id TEXT PRIMARY KEY,

    -- 사용자·설비·사건 테이블과의 연결은 해당 테이블 구현 후 추가한다.
    assignee_id TEXT,
    process_id TEXT,
    asset_id TEXT,
    incident_id TEXT,

    creation_type TEXT NOT NULL
        CHECK (creation_type IN ('AI', 'MANUAL')),

    data_origin TEXT NOT NULL
        CHECK (data_origin IN ('LIVE', 'REPLAY', 'SYNTHETIC')),

    report_status TEXT NOT NULL DEFAULT 'DRAFT'
        CHECK (
            report_status IN (
                'DRAFT',
                'SUBMITTED',
                'REVIEWED',
                'APPROVED',
                'REJECTED'
            )
        ),

    current_version INTEGER NOT NULL DEFAULT 1
        CHECK (current_version > 0),

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);


-- 보고서 버전별 내용
CREATE TABLE report_versions (
    version_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    report_id TEXT NOT NULL REFERENCES reports (report_id),
    version_no INTEGER NOT NULL CHECK (version_no > 0),

    -- 해당 버전을 작성한 직원
    author_id TEXT,

    -- 보고서 작성에 사용한 당시의 시스템 정보와 AI 분석
    incident_snapshot JSONB,
    ai_analysis_snapshot JSONB,

    -- 직원이 폼에서 작성한 내용
    form_data JSONB NOT NULL DEFAULT '{}'::JSONB,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    submitted_at TIMESTAMPTZ,

    CONSTRAINT report_version_unique
        UNIQUE (report_id, version_no),

    CONSTRAINT incident_snapshot_object
        CHECK (
            incident_snapshot IS NULL
            OR jsonb_typeof(incident_snapshot) = 'object'
        ),

    CONSTRAINT ai_analysis_snapshot_object
        CHECK (
            ai_analysis_snapshot IS NULL
            OR jsonb_typeof(ai_analysis_snapshot) = 'object'
        ),

    CONSTRAINT form_data_object
        CHECK (jsonb_typeof(form_data) = 'object')
);


-- 보고서의 현재 버전은 실제로 존재하는 해당 보고서의 버전이어야 한다.
-- 보고서와 첫 버전을 같은 작업에서 생성할 수 있도록 저장 완료 시 검사한다.
ALTER TABLE reports
    ADD CONSTRAINT report_current_version_fk
    FOREIGN KEY (report_id, current_version)
    REFERENCES report_versions (report_id, version_no)
    DEFERRABLE INITIALLY DEFERRED;