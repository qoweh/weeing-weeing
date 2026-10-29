"""문서 물리 삭제 전환: 이전에 삭제 완료된 문서 행만 정리한다.

Revision ID: 0006
Revises: 0005
기존 deleted는 벡터 삭제가 성공한 행이다. 활성 문서와 삭제 실패·진행 중 행은 유지한다.
미공유 문서 정리 0005를 먼저 적용한 DB에는 공식 0005의 analysis_job이 없을 수 있다.
테이블이 없는 경우에만 공식 마이그레이션을 실행해 데이터 삭제 없이 보완한다.
"""

import sqlalchemy as sa
from alembic import op
from alembic.script import ScriptDirectory

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("analysis_job"):
        scripts = ScriptDirectory.from_config(op.get_context().config)
        scripts.get_revision("0005").module.upgrade()
    document = sa.table(
        "document", sa.column("status"), sa.column("doc_type"), sa.column("origin")
    )
    op.execute(
        document.delete().where(
            document.c.status == "deleted",
            document.c.doc_type.in_(("manual", "sop", "rule")),
            document.c.origin.in_(("seed", "upload")),
        )
    )


def downgrade() -> None:
    # 실제 삭제된 행은 되살리지 않는다. analysis_job은 공식 0005의 소유이므로 유지한다.
    pass
