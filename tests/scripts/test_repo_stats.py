"""레포 활동 차트 집계. GitHub API·Chrome 없이 순수 함수와 실패 처리만 검사한다."""

import importlib.util
import json
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def script():
    spec = importlib.util.spec_from_file_location(
        "repo_stats", ROOT / "scripts/repo_stats.py"
    )
    module = importlib.util.module_from_spec(spec)
    # dataclass가 자기 모듈을 sys.modules에서 찾으므로 실행 전에 등록한다
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rs = script()


def utc(*args):
    return datetime(*args, tzinfo=UTC)


@pytest.mark.parametrize(
    ("subject", "expected"),
    [
        ("feat: 챗봇 추가 (#12)", "feat"),
        ("fix(api)!: 인증 오류", "fix"),
        ("Docs: README", "docs"),
        ("perf: 빠르게", "other"),
        ("Merge branch 'dev'", "other"),
    ],
)
def test_commit_type(subject, expected):
    assert rs.commit_type(subject) == expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/weeing_weeing/agent/chat.py", "agent"),
        ("src/weeing_weeing/__init__.py", "other"),
        ("frontend/src/app/page.tsx", "frontend"),
        ("hmi/web/src/App.jsx", "hmi"),
        ("docs/ARCHITECTURE.md", "docs"),
        ("README.md", "docs"),
        (".github/workflows/ci.yml", "infra"),
        ("docker-compose.yml", "infra"),
        ("pyproject.toml", "other"),
    ],
)
def test_area_of(path, expected):
    assert rs.area_of(path) == expected


@pytest.mark.parametrize(
    ("hours", "expected"),
    [(0.5, "< 1h"), (1, "1-6h"), (23.9, "6-24h"), (24, "1-3d"), (100, "> 3d")],
)
def test_merge_bucket(hours, expected):
    assert rs.merge_bucket(hours) == expected


def test_cumulative_counts_by_kst_day():
    days = [date(2026, 10, 20), date(2026, 10, 21)]
    # UTC 10/20 15:30 = KST 10/21 00:30 → 다음 날로 센다
    events = [utc(2026, 10, 20, 1), utc(2026, 10, 20, 15, 30)]
    assert rs.cumulative(events, days) == [1, 2]


def test_build_stats_summary_and_series():
    commits = [
        rs.Commit(
            utc(2026, 10, 20, 1), "feat: a", ["src/weeing_weeing/rag/x.py", "docs/a.md"]
        ),
        rs.Commit(utc(2026, 10, 21, 1), "fix: b", ["src/weeing_weeing/rag/y.py"]),
    ]
    prs = [
        rs.Item(
            "alice", utc(2026, 10, 20, 0), utc(2026, 10, 20, 2), utc(2026, 10, 20, 2)
        ),
        rs.Item("bob", utc(2026, 10, 21, 0), utc(2026, 10, 21, 1), None),
        rs.Item("dependabot[bot]", utc(2026, 10, 21, 0), None, None),
    ]
    issues = [
        rs.Item("alice", utc(2026, 10, 20, 0), utc(2026, 10, 21, 0)),
        rs.Item("bob", utc(2026, 10, 21, 0), None),
    ]

    stats = rs.build_stats(commits, prs, issues, today=date(2026, 10, 22))

    s = stats["summary"]
    assert (s["start"], s["end"], s["days"]) == ("2026-10-20", "2026-10-22", 3)
    assert (s["commits"], s["prs_merged"], s["prs_total"]) == (2, 1, 3)
    assert (s["issues_closed"], s["issues_total"], s["contributors"]) == (1, 2, 2)
    assert s["median_merge_hours"] == 2.0
    assert stats["growth"]["series"]["Commits"] == [1, 2, 2]
    assert stats["growth"]["series"]["Issues closed"] == [0, 1, 1]
    assert stats["activity"] == {
        "labels": ["20", "21", "22"],
        "values": [1, 1, 0],
        "unit": "day",
    }
    assert stats["types"] == {"feat": 1, "fix": 1}
    assert stats["areas"] == {"rag": 2, "docs": 1}
    assert stats["merge"]["1-6h"] == 1


def test_build_stats_switches_to_weekly_after_a_month():
    commits = [
        rs.Commit(utc(2026, 9, 1, 1), "feat: a"),
        rs.Commit(utc(2026, 9, 9, 1), "feat: b"),
    ]
    stats = rs.build_stats(commits, [], [], today=date(2026, 10, 10))
    assert stats["activity"]["unit"] == "week"
    assert stats["activity"]["values"][:2] == [1, 1]
    assert stats["summary"]["median_merge_hours"] is None


def test_build_stats_requires_data():
    with pytest.raises(SystemExit):
        rs.build_stats([], [], [], today=date(2026, 10, 22))


def test_gh_failure_stops_with_message(monkeypatch):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="HTTP 404")

    monkeypatch.setattr(rs.subprocess, "run", fake_run)
    with pytest.raises(SystemExit, match="HTTP 404"):
        rs.gh_paginate("repos/x/y/pulls")


def test_fetch_items_excludes_pull_requests_from_issues(monkeypatch):
    pages = {
        "pulls": [
            [
                {
                    "user": {"login": "a"},
                    "created_at": "2026-10-20T00:00:00Z",
                    "closed_at": None,
                    "merged_at": None,
                }
            ]
        ],
        "issues": [
            [
                {
                    "user": {"login": "a"},
                    "created_at": "2026-10-20T00:00:00Z",
                    "closed_at": None,
                },
                {
                    "user": {"login": "a"},
                    "created_at": "2026-10-20T00:00:00Z",
                    "closed_at": None,
                    "pull_request": {},
                },
            ]
        ],
    }

    def fake_run(cmd, **kwargs):
        key = "pulls" if "/pulls?" in cmd[-1] else "issues"
        return subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps(pages[key]), stderr=""
        )

    monkeypatch.setattr(rs.subprocess, "run", fake_run)
    prs, issues = rs.fetch_items("o/r")
    assert len(prs) == 1
    assert len(issues) == 1


def test_extract_svgs_reads_serialized_output():
    payload = {
        name: f'<svg xmlns="http://www.w3.org/2000/svg"><svg></svg>{name}</svg>'
        for name in rs.CHARTS
    }
    dom = f'<html><script type="application/json" id="svg-out">{json.dumps(payload)}</script></html>'
    assert rs.extract_svgs(dom) == payload


def test_extract_svgs_fails_when_chart_script_did_not_run():
    with pytest.raises(SystemExit, match="chart.xkcd"):
        rs.extract_svgs("<html><body></body></html>")


def test_build_html_pins_chart_library_with_integrity():
    stats = rs.build_stats(
        [rs.Commit(utc(2026, 10, 20, 1), "feat: a")], [], [], today=date(2026, 10, 20)
    )
    html = rs.build_html(stats)
    assert f'src="{rs.CHART_XKCD_URL}" integrity="{rs.CHART_XKCD_SRI}"' in html
    assert all(f'id="{name}"' in html for name in rs.CHARTS)


def test_readme_lists_summary_and_images():
    stats = rs.build_stats(
        [rs.Commit(utc(2026, 10, 20, 1), "feat: a")], [], [], today=date(2026, 10, 20)
    )
    text = rs.build_readme(stats, "https://example.test/run/1")
    assert "| 커밋 | 1 |" in text
    assert "[실행 기록](https://example.test/run/1)" in text
    assert "![growth](growth.svg)" in text
