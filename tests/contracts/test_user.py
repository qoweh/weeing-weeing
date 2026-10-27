"""UserAccount: 사번 형식, 직책은 Role 4종, 비밀번호 칸은 없다."""

import pytest
from pydantic import ValidationError

from weeing_weeing.contracts import Role, UserAccount


def test_defaults_and_role():
    user = UserAccount(employee_no="E1001", name="김점검", role=Role.INSPECTOR)
    assert user.role == "현장 점검자"
    assert (user.is_admin, user.is_active) == (False, True)
    assert "password" not in UserAccount.model_fields


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("employee_no", "공백 있음"),
        ("employee_no", "x"),
        ("name", ""),
        ("role", "사장"),
    ],
)
def test_invalid_values_are_rejected(field, value):
    data = {"employee_no": "E1001", "name": "김점검", "role": Role.INSPECTOR}
    with pytest.raises(ValidationError):
        UserAccount(**(data | {field: value}))
