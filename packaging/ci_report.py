"""Publish CI failure details as a GitHub issue comment.

The build workflow runs on GitHub-hosted runners.  When a test step fails the
raw job log is not always reachable from every environment, so this helper
collects what matters (the tail of every captured step log plus the failing
test cases from the JUnit reports) and posts it as a comment on a single
tracking issue.  The issue body is plain markdown, so it is easy to read - and
to fetch over the API - even when log downloads are blocked.

Usage (from a workflow step)::

    python packaging/ci_report.py --title "CI failure reports" \
        --logs ci-logs --reports test-results

Requires ``GH_TOKEN`` (or ``GITHUB_TOKEN``) in the environment.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

MAX_LOG_LINES = 120
MAX_BODY = 60_000


def run_gh(args: list[str], *, input_text: str | None = None) -> str:
    result = subprocess.run(
        ["gh", *args],
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def repo_slug() -> str:
    return os.environ.get("GITHUB_REPOSITORY") or run_gh(
        ["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"]
    ).strip()


def tail(path: Path, lines: int = MAX_LOG_LINES) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:  # pragma: no cover - defensive
        return f"(could not read {path}: {exc})"
    if len(content) > lines:
        content = [f"... {len(content) - lines} earlier lines omitted ...", *content[-lines:]]
    return "\n".join(content)


def junit_failures(reports: Path) -> list[str]:
    """Return one markdown block per failing test case."""
    blocks: list[str] = []
    if not reports.exists():
        return blocks
    for xml_path in sorted(reports.glob("*.xml")):
        try:
            root = ET.parse(xml_path).getroot()
        except ET.ParseError as exc:
            blocks.append(f"### {xml_path.name}\n\n(could not parse: {exc})")
            continue
        suites = [root] if root.tag == "testsuite" else list(root)
        header = (
            f"### {xml_path.name} - "
            f"{root.get('tests', '?')} tests, {root.get('failures', '?')} failures, "
            f"{root.get('errors', '?')} errors, {root.get('time', '?')}s"
        )
        lines = [header]
        for suite in suites:
            for case in suite.iter("testcase"):
                problems = [*case.findall("failure"), *case.findall("error")]
                if not problems:
                    continue
                for problem in problems:
                    message = (problem.get("message") or "").strip()
                    text = (problem.text or "").strip()
                    lines.append(
                        f"\n<details><summary><b>{case.get('classname', '')}::"
                        f"{case.get('name', '')}</b> - {message[:160]}</summary>\n\n"
                        f"```\n{(text or message)[:4000]}\n```\n</details>"
                    )
        blocks.append("\n".join(lines))
    return blocks


def build_body(logs: Path, reports: Path, extra: str = "") -> str:
    parts: list[str] = []
    run_url = ""
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if repo and run_id:
        run_url = f"{server}/{repo}/actions/runs/{run_id}"
    parts.append(
        f"**Workflow run:** {run_url or '(local)'}\n"
        f"**Ref:** `{os.environ.get('GITHUB_REF_NAME', '?')}` "
        f"(`{os.environ.get('GITHUB_SHA', '?')[:12]}`)\n"
        f"**Job:** {os.environ.get('GITHUB_JOB', '?')}"
    )
    if extra:
        parts.append(extra)
    parts.extend(junit_failures(reports))
    if logs.exists():
        for log_path in sorted(logs.glob("*.log")):
            parts.append(f"### log: {log_path.name}\n\n```\n{tail(log_path)}\n```")
    body = "\n\n".join(parts)
    if len(body) > MAX_BODY:
        body = body[:MAX_BODY] + "\n\n... (truncated) ..."
    return body


def post_comment(title: str, body: str) -> None:
    repo = repo_slug()
    issues = json.loads(
        run_gh(
            [
                "api",
                f"repos/{repo}/issues?state=open&per_page=100",
                "--jq",
                "[.[] | select(.pull_request == null) | {number, title}]",
            ]
        )
    )
    number = next((issue["number"] for issue in issues if issue["title"] == title), None)
    if number is None:
        created = run_gh(
            [
                "api",
                "--method",
                "POST",
                f"repos/{repo}/issues",
                "-f",
                f"title={title}",
                "-f",
                "body=Automated CI diagnostics. Each failing run appends a comment.",
            ]
        )
        number = json.loads(created)["number"]
    run_gh(
        [
            "api",
            "--method",
            "POST",
            f"repos/{repo}/issues/{number}/comments",
            "-f",
            f"body={body}",
        ]
    )
    print(f"posted diagnostics to issue #{number}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", default="CI failure reports")
    parser.add_argument("--logs", default="ci-logs")
    parser.add_argument("--reports", default="test-results")
    parser.add_argument("--extra", default="")
    parser.add_argument("--dry-run", action="store_true", help="print instead of posting")
    args = parser.parse_args(argv)

    body = build_body(Path(args.logs), Path(args.reports), extra=args.extra)
    if args.dry_run:
        print(body)
        return 0
    try:
        post_comment(args.title, body)
    except Exception as exc:  # pragma: no cover - never fail the job for diagnostics
        print(f"could not post diagnostics: {exc}", file=sys.stderr)
        print(body)
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
