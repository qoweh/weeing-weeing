"""실제 서버·Docker 없이 배포 shell의 대상 서비스와 실패 복원을 검증한다."""

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def bash_path(path):
    value = path.as_posix()
    return f"/{value[0].lower()}/{value[3:]}" if os.name == "nt" else value


@pytest.mark.parametrize(
    "service,failure",
    [
        ("api", "none"),
        ("api", "pull"),
        ("api", "up"),
        ("api", "smoke"),
        ("web", "none"),
        ("web", "pull"),
        ("web", "up"),
        ("web", "tls"),
    ],
)
def test_one_service_deploy_preserves_other_tags_and_rolls_back(
    tmp_path, service, failure
):
    bash = (
        "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
    )
    if not bash or not Path(bash).is_file():
        pytest.skip("Bash가 필요합니다")
    workflow = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
    marker = "WEB_ONLY='$WEB_ONLY' bash -s\" <<'EOF'\n"
    remote = textwrap.dedent(
        workflow.split(marker, 1)[1].split("\n          EOF", 1)[0]
    )
    remote = remote.replace("cd ~/weeing-weeing", 'cd "$CASE_DIR"')
    if sys.platform == "darwin":
        # 운영 Ubuntu의 GNU sed와 달리 macOS의 BSD sed는 백업 접미사가 필요하다.
        remote = remote.replace("sed -i ", "sed -i '' ")
    initial = "IMAGE_TAG=original\nAPI_IMAGE_TAG=old-api\nWEB_IMAGE_TAG=old-web\n"
    (tmp_path / ".env").write_text(initial, encoding="utf-8")  # fake file only
    tools = tmp_path / "bin"
    tools.mkdir()
    docker = tools / "docker"
    docker.write_text(
        textwrap.dedent(r"""
        #!/bin/sh
        case "$1 $2" in
          'inspect --format') printf 'ghcr.io/fake/app-%s:old-%s\n' "$TEST_SERVICE" "$TEST_SERVICE" ;;
          'compose ps') printf 'owned-fake-container\n' ;;
          'compose pull')
                printf 'pull %s\n' "$4" >> "$CASE_DIR/operations"
            [ "$TEST_FAILURE" != pull ] ;;
          'compose up')
            for arg in "$@"; do target="$arg"; done
            printf 'up %s\n' "$target" >> "$CASE_DIR/operations"
            if [ "$TEST_FAILURE" = up ] && [ ! -f "$CASE_DIR/first-up" ]; then
              touch "$CASE_DIR/first-up"
              exit 1
            fi ;;
          'compose exec')
            printf '%s\n' "$*" >> "$CASE_DIR/smoke-calls"
            [ "$TEST_FAILURE" != smoke ] ;;
          'logout ghcr.io') : ;;
          *) exit 90 ;;
        esac
            """).lstrip(),
        encoding="utf-8",
        newline="\n",
    )
    docker.chmod(0o755)
    curl = tools / "curl"
    curl.write_text(
        '#!/bin/sh\nprintf "probe\\n" >> "$CASE_DIR/tls-calls"\n[ "$TEST_FAILURE" != tls ]\n',
        encoding="utf-8",
        newline="\n",
    )
    curl.chmod(0o755)
    sleep = tools / "sleep"
    sleep.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8", newline="\n")
    sleep.chmod(0o755)
    script = tmp_path / "run.sh"
    prefix = 'export PATH="$CASE_DIR/bin:/usr/bin:/bin"\n[ "$(command -v docker)" = "$CASE_DIR/bin/docker" ] || exit 91\n[ "$(command -v curl)" = "$CASE_DIR/bin/curl" ] || exit 92\n'
    script.write_text(prefix + remote, encoding="utf-8", newline="\n")
    environment = dict(os.environ)
    environment.update(
        CASE_DIR=bash_path(tmp_path),
        TEST_SERVICE=service,
        TEST_FAILURE=failure,
        API_ONLY="true" if service == "api" else "false",
        WEB_ONLY="true" if service == "web" else "false",
        TAG="new-sha",
    )
    result = subprocess.run(
        [bash, bash_path(script)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == (0 if failure == "none" else 1), result.stderr
    values = dict(
        line.split("=", 1)
        for line in (tmp_path / ".env").read_text().splitlines()
        if line
    )
    assert values["IMAGE_TAG"] == "original"
    other = "web" if service == "api" else "api"
    assert values[f"{other.upper()}_IMAGE_TAG"] == f"old-{other}"
    assert values[f"{service.upper()}_IMAGE_TAG"] == (
        "new-sha" if failure == "none" else f"old-{service}"
    )
    operations = (tmp_path / "operations").read_text().splitlines()
    assert operations == [f"pull {service}"] + [f"up {service}"] * (
        0 if failure == "pull" else 2 if failure in {"up", "tls", "smoke"} else 1
    )
    if service == "web" and failure in {"none", "tls"}:
        assert len((tmp_path / "tls-calls").read_text().splitlines()) == (
            12 if failure == "tls" else 1
        )
    else:
        assert not (tmp_path / "tls-calls").exists()

    smoke_calls = tmp_path / "smoke-calls"
    if service == "api" and failure in {"none", "smoke"}:
        assert smoke_calls.read_text().splitlines() == [
            "compose exec -T api python scripts/check_ml_runtime.py"
        ]
    else:
        assert not smoke_calls.exists()
