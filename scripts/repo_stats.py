"""레포 활동(커밋·PR·이슈)을 손그림 스타일 차트(chart.xkcd)로 만든다.

GitHub Actions의 "Repo stats" 워크플로가 실행한다(.github/workflows/repo-stats.yml).
결과는 repo-stats 브랜치에 README.md와 SVG로 올라가 발표 자료에 그대로 쓸 수 있다.

로컬 실행(gh 로그인 필요, 표준 라이브러리만 사용):
    python3 scripts/repo_stats.py --repo qoweh/weeing-weeing --branch origin/dev --out build/repo-stats \
        --chrome "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
CHART_XKCD_URL = "https://cdn.jsdelivr.net/npm/chart.xkcd@2.0.12/dist/chart.xkcd.min.js"
CHART_XKCD_SRI = (
    "sha384-VCpo58LOJanLwWG+GO/+FtIEB8N6Wh9+FjGxpbnPmzZcrJuS3pbgzcBnlVNOBO1P"
)
GH_TIMEOUT_SEC = 120
CHROME_TIMEOUT_SEC = 120

COMMIT_TYPES = ("feat", "fix", "docs", "chore", "refactor", "test")
MERGE_BUCKETS = ("< 1h", "1-6h", "6-24h", "1-3d", "> 3d")
SRC_MODULES = (
    "agent",
    "api",
    "contracts",
    "db",
    "detector",
    "ingest",
    "ml",
    "plc",
    "rag",
)
CHARTS = ("growth", "daily", "types", "areas", "merge")


@dataclass
class Commit:
    when: datetime
    subject: str
    files: list[str] = field(default_factory=list)


@dataclass
class Item:
    """PR 또는 이슈."""

    author: str
    created: datetime
    closed: datetime | None
    merged: datetime | None = None


# ── 분류·집계 (순수 함수) ─────────────────────────────


def commit_type(subject: str) -> str:
    m = re.match(r"^\s*([a-zA-Z]+)(\([^)]*\))?!?:", subject)
    kind = m.group(1).lower() if m else ""
    return kind if kind in COMMIT_TYPES else "other"


def area_of(path: str) -> str:
    parts = path.split("/")
    if (
        parts[:2] == ["src", "weeing_weeing"]
        and len(parts) > 3
        and parts[2] in SRC_MODULES
    ):
        return parts[2]
    top = parts[0]
    if top in ("frontend", "tests", "data", "scripts"):
        return top
    if top == "hmi":
        return "hmi"
    if top == "docs" or path.endswith(".md"):
        return "docs"
    if top in ("deploy", "ops", ".github") or top.startswith("docker-compose"):
        return "infra"
    return "other"


def merge_bucket(hours: float) -> str:
    if hours < 1:
        return MERGE_BUCKETS[0]
    if hours < 6:
        return MERGE_BUCKETS[1]
    if hours < 24:
        return MERGE_BUCKETS[2]
    if hours < 72:
        return MERGE_BUCKETS[3]
    return MERGE_BUCKETS[4]


def kst_day(dt: datetime) -> date:
    return dt.astimezone(KST).date()


def day_range(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def cumulative(events: list[datetime], days: list[date]) -> list[int]:
    per_day = Counter(kst_day(e) for e in events)
    total, out = 0, []
    for d in days:
        total += per_day.get(d, 0)
        out.append(total)
    return out


def build_stats(
    commits: list[Commit], prs: list[Item], issues: list[Item], today: date
) -> dict:
    all_dates = (
        [c.when for c in commits]
        + [p.created for p in prs]
        + [i.created for i in issues]
    )
    if not all_dates:
        raise SystemExit("집계할 커밋·PR·이슈가 없습니다.")
    start = min(kst_day(d) for d in all_dates)
    days = day_range(start, max(today, start))

    merged = [p for p in prs if p.merged]
    closed_issues = [i for i in issues if i.closed]
    merge_hours = [(p.merged - p.created).total_seconds() / 3600 for p in merged]

    weekly = len(days) > 31
    per_commit_day = Counter(kst_day(c.when) for c in commits)
    if weekly:
        buckets: Counter = Counter()
        for d, n in per_commit_day.items():
            buckets[(d - start).days // 7] += n
        n_weeks = (len(days) + 6) // 7
        activity = {
            "labels": [f"W{w + 1}" for w in range(n_weeks)],
            "values": [buckets.get(w, 0) for w in range(n_weeks)],
            "unit": "week",
        }
    else:
        activity = {
            "labels": [str(d.day) for d in days],
            "values": [per_commit_day.get(d, 0) for d in days],
            "unit": "day",
        }

    types = Counter(commit_type(c.subject) for c in commits)
    areas: Counter = Counter()
    for c in commits:
        areas.update({area_of(f) for f in c.files})
    top_areas = [(a, n) for a, n in areas.most_common() if a != "other"][:10]

    contributors = {p.author for p in prs if not p.author.endswith("[bot]")}
    return {
        "generated_at": datetime.now(KST).isoformat(timespec="minutes"),
        "summary": {
            "start": start.isoformat(),
            "end": days[-1].isoformat(),
            "days": len(days),
            "commits": len(commits),
            "prs_total": len(prs),
            "prs_merged": len(merged),
            "issues_total": len(issues),
            "issues_closed": len(closed_issues),
            "contributors": len(contributors),
            "median_merge_hours": round(statistics.median(merge_hours), 1)
            if merge_hours
            else None,
        },
        "growth": {
            "days": [d.isoformat() for d in days],
            "series": {
                "Commits": cumulative([c.when for c in commits], days),
                "PRs merged": cumulative([p.merged for p in merged], days),
                "Issues opened": cumulative([i.created for i in issues], days),
                "Issues closed": cumulative([i.closed for i in closed_issues], days),
            },
        },
        "activity": activity,
        "types": {k: types[k] for k in (*COMMIT_TYPES, "other") if types[k]},
        "areas": dict(top_areas),
        "merge": {
            b: Counter(merge_bucket(h) for h in merge_hours)[b] for b in MERGE_BUCKETS
        },
    }


# ── 수집 ────────────────────────────────────────────


def _ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def gh_paginate(path: str) -> list[dict]:
    """gh CLI로 REST API를 모두 읽는다. 인증은 gh(GH_TOKEN)가 처리한다."""
    try:
        res = subprocess.run(
            ["gh", "api", "--paginate", "--slurp", path],
            capture_output=True,
            text=True,
            timeout=GH_TIMEOUT_SEC,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(f"gh api 실행 실패: {path}: {exc}") from exc
    if res.returncode != 0:
        raise SystemExit(
            f"gh api 실패({res.returncode}): {path}: {res.stderr.strip()[:500]}"
        )
    return [row for page in json.loads(res.stdout) for row in page]


def fetch_items(repo: str) -> tuple[list[Item], list[Item]]:
    prs = [
        Item(
            p["user"]["login"],
            _ts(p["created_at"]),
            _ts(p["closed_at"]),
            _ts(p["merged_at"]),
        )
        for p in gh_paginate(f"repos/{repo}/pulls?state=all&per_page=100")
    ]
    issues = [
        Item(i["user"]["login"], _ts(i["created_at"]), _ts(i["closed_at"]))
        for i in gh_paginate(f"repos/{repo}/issues?state=all&per_page=100")
        if "pull_request" not in i
    ]
    return prs, issues


def read_commits(branch: str) -> list[Commit]:
    marker = "\x1e"
    out = subprocess.run(
        [
            "git",
            "log",
            branch,
            "--no-merges",
            f"--format={marker}%cI%x09%s",
            "--name-only",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    commits = []
    for block in out.split(marker)[1:]:
        head, *files = block.strip("\n").split("\n")
        when, _, subject = head.partition("\t")
        commits.append(Commit(_ts(when), subject, [f for f in files if f]))
    return commits


# ── 그리기 ──────────────────────────────────────────


def build_html(stats: dict) -> str:
    data = json.dumps(stats, ensure_ascii=False).replace("</", "<\\/")
    charts = json.dumps(list(CHARTS))
    svgs = "\n".join(
        f'<svg id="{name}" width="860" height="500"></svg>' for name in CHARTS
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Repo stats</title>
<script src="{CHART_XKCD_URL}" integrity="{CHART_XKCD_SRI}" crossorigin="anonymous"></script>
<style>body{{background:#fff;margin:0}} svg{{display:block}}</style></head>
<body>
{svgs}
<script>
const S = {data};
const X = chartXkcd, pos = X.config.positionType;
const g = S.growth;
new X.XY(document.getElementById("growth"), {{
  title: "Project growth", xLabel: "Date", yLabel: "Total",
  data: {{ datasets: Object.entries(g.series).map(([label, ys]) => ({{
    label, data: g.days.map((d, i) => ({{ x: d, y: ys[i] }})) }})) }},
  options: {{ xTickCount: 4, yTickCount: 5, showLine: true, dotSize: 0.4,
    timeFormat: "MM/DD", legendPosition: pos.upLeft }},
}});
new X.Bar(document.getElementById("daily"), {{
  title: S.activity.unit === "week" ? "Commits per week" : `Commits per day (${{S.summary.start.slice(5)}} ~)`,
  xLabel: "", yLabel: "Commits",
  data: {{ labels: S.activity.labels, datasets: [{{ data: S.activity.values }}] }},
  options: {{ yTickCount: 4 }},
}});
new X.Pie(document.getElementById("types"), {{
  title: "What we committed",
  data: {{ labels: Object.keys(S.types), datasets: [{{ data: Object.values(S.types) }}] }},
  options: {{ innerRadius: 0.5, legendPosition: pos.upRight }},
}});
new X.Bar(document.getElementById("areas"), {{
  title: "Where we worked", xLabel: "", yLabel: "Commits touching",
  data: {{ labels: Object.keys(S.areas), datasets: [{{ data: Object.values(S.areas) }}] }},
  options: {{ yTickCount: 4 }},
}});
new X.Bar(document.getElementById("merge"), {{
  title: "PR open -> merge time", xLabel: "", yLabel: "PRs",
  data: {{ labels: Object.keys(S.merge), datasets: [{{ data: Object.values(S.merge) }}] }},
  options: {{ yTickCount: 4 }},
}});
const out = document.createElement("script");
out.type = "application/json";
out.id = "svg-out";
out.textContent = JSON.stringify(Object.fromEntries(
  {charts}.map(id => [id, new XMLSerializer().serializeToString(document.getElementById(id))])
)).replace(/</g, "\\\\u003c");
document.body.appendChild(out);
</script>
</body></html>
"""


def extract_svgs(dom: str) -> dict[str, str]:
    """index.html이 XMLSerializer로 만들어 둔 SVG 문자열을 꺼낸다(중첩 svg도 온전히 유지)."""
    m = re.search(
        r'<script type="application/json" id="svg-out">(.*?)</script>', dom, re.S
    )
    if not m:
        raise SystemExit(
            "차트 그리기 실패: chart.xkcd를 불러오지 못했거나 스크립트 오류가 났습니다."
        )
    found = json.loads(m.group(1))
    missing = [name for name in CHARTS if not found.get(name, "").startswith("<svg")]
    if missing:
        raise SystemExit(f"차트 SVG를 찾지 못했습니다: {missing}")
    return {name: found[name] for name in CHARTS}


def render(html_path: Path, chrome: str) -> dict[str, str]:
    try:
        res = subprocess.run(
            [
                chrome,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--virtual-time-budget=15000",
                "--dump-dom",
                html_path.resolve().as_uri(),
            ],
            capture_output=True,
            text=True,
            timeout=CHROME_TIMEOUT_SEC,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(f"Chrome 실행 실패: {exc}") from exc
    return extract_svgs(res.stdout)


def build_readme(stats: dict, run_url: str | None) -> str:
    s = stats["summary"]
    median = (
        f"{s['median_merge_hours']}시간" if s["median_merge_hours"] is not None else "-"
    )
    source = f" · [실행 기록]({run_url})" if run_url else ""
    rows = [
        ("기간", f"{s['start']} ~ {s['end']} ({s['days']}일)"),
        ("커밋", s["commits"]),
        ("PR", f"{s['prs_merged']} 병합 / {s['prs_total']} 전체"),
        ("이슈", f"{s['issues_closed']} 완료 / {s['issues_total']} 전체"),
        ("PR 작성자", f"{s['contributors']}명"),
        ("PR 병합까지 중앙값", median),
    ]
    table = "\n".join(f"| {k} | {v} |" for k, v in rows)
    images = "\n\n".join(f"![{n}]({n}.svg)" for n in CHARTS)
    return f"""# 레포 활동 차트

자동 생성 파일입니다. 직접 고치지 말고 Actions의 **Repo stats → Run workflow**로 다시 만듭니다.
갱신: {stats["generated_at"]} (KST){source}

| 항목 | 값 |
|---|---|
{table}

{images}
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--branch", default="HEAD", help="커밋을 셀 브랜치(git log 대상)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument(
        "--chrome", default="google-chrome", help="헤드리스 Chrome 실행 파일"
    )
    ap.add_argument("--run-url", default=None, help="README에 남길 Actions 실행 주소")
    args = ap.parse_args(argv)

    prs, issues = fetch_items(args.repo)
    commits = read_commits(args.branch)
    stats = build_stats(commits, prs, issues, datetime.now(UTC).astimezone(KST).date())

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "data.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    html_path = args.out / "index.html"
    html_path.write_text(build_html(stats), encoding="utf-8")
    for name, svg in render(html_path, args.chrome).items():
        (args.out / f"{name}.svg").write_text(svg, encoding="utf-8")
    (args.out / "README.md").write_text(
        build_readme(stats, args.run_url), encoding="utf-8"
    )
    print(json.dumps(stats["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
