"""사용자 계정 계약(#62). 비밀번호·세션 토큰은 들어가지 않는다(db 내부에만 있음).

출처: 노션 '전체 할 일 정리 > 8. 사용자·권한'(직책 4종 권한표, 간단 로그인).
직책(Role)은 업무 권한(결재 단계 등), is_admin은 계정 관리 권한이다. 둘은 따로 준다.
계정 관리자는 직책과 관계없이 모든 직책의 업무 권한도 가진다(D-36).
"""

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from weeing_weeing.contracts.report import Role

EMPLOYEE_NO_PATTERN = r"^[A-Za-z0-9_-]{2,32}$"


class UserAccount(BaseModel):
    model_config = ConfigDict(frozen=True)

    # 사번. 보고서 ActionTaken.by·ApprovalStep.user와 같은 값
    employee_no: str = Field(pattern=EMPLOYEE_NO_PATTERN)
    name: str = Field(min_length=1, max_length=64)
    role: Role
    is_admin: bool = False  # 계정 관리 + 모든 직책의 업무 권한(D-36)
    is_active: bool = True  # False면 로그인·기존 세션 모두 거부
    created_at: AwareDatetime | None = None
    last_login_at: AwareDatetime | None = None
