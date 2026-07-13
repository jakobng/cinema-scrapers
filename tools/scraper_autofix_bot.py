#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from email.message import EmailMessage
import json
import os
import re
import smtplib
import subprocess
import sys
import textwrap
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / ".github" / "autofix-policy.json"
STATE_PATH = ROOT / "logs" / "autofix_state.json"
HEALTH_MONITOR_PATH = ROOT / "tools" / "cinema_health_monitor.py"


def run(cmd: list[str], *, check: bool = True, input_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=ROOT,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=check,
    )


def gh_json(args: list[str]) -> object:
    completed = run(["gh", *args])
    return json.loads(completed.stdout or "null")


def gh_text(args: list[str], *, check: bool = True) -> str:
    return run(["gh", *args], check=check).stdout


def load_policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def ensure_clean_worktree() -> None:
    status = run(["git", "status", "--porcelain"]).stdout.strip()
    if status:
        raise SystemExit("Worktree is not clean; commit or stash local changes before running the bot.")


def current_branch() -> str:
    return run(["git", "branch", "--show-current"]).stdout.strip()


def current_week_key() -> str:
    year, week, _ = datetime.now(timezone.utc).isocalendar()
    return f"{year}-W{week:02d}"


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def should_skip_weekly_run(args: argparse.Namespace) -> bool:
    if args.ci or args.dry_run or args.force:
        return False
    state = load_state(args.state_file)
    return state.get("last_successful_week") == current_week_key()


def mark_weekly_run_success(args: argparse.Namespace) -> None:
    if args.dry_run:
        return
    state = load_state(args.state_file)
    state["last_successful_week"] = current_week_key()
    state["last_successful_run_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    save_state(args.state_file, state)


def infer_city(issue: dict, policy: dict) -> str | None:
    labels = {label["name"].lower() for label in issue.get("labels", [])}
    for city in policy["cities"]:
        if city in labels:
            return city
    text = f"{issue.get('title', '')}\n{issue.get('body', '')}".lower()
    for city in policy["cities"]:
        if city in text:
            return city
    return None


def extract_run_id(text: str) -> str | None:
    match = re.search(r"/actions/runs/(\d+)", text or "")
    return match.group(1) if match else None


def get_run_logs(run_id: str | None, limit: int) -> str:
    if not run_id:
        return ""
    completed = run(["gh", "run", "view", run_id, "--log"], check=False)
    logs = completed.stdout
    if len(logs) > limit:
        return logs[-limit:]
    return logs


def list_candidate_issues(policy: dict, limit: int) -> list[dict]:
    label = policy["labels"]["candidate"]
    return gh_json(
        [
            "issue",
            "list",
            "--state",
            "open",
            "--label",
            label,
            "--limit",
            str(limit),
            "--json",
            "number,title,body,labels,url",
        ]
    )


def run_health_monitor(args: argparse.Namespace) -> None:
    if args.skip_health_monitor:
        return
    command = [
        sys.executable,
        str(HEALTH_MONITOR_PATH),
        "--sample-size",
        str(args.health_sample_size),
        "--create-issues",
    ]
    if args.email_summary:
        command.append("--email-summary")
    if args.dry_run:
        command.append("--dry-run")
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    print(completed.stdout)
    if completed.returncode != 0:
        print("Health monitor found failed checks; continuing so candidate issues can still be reviewed.", file=sys.stderr)


def call_chat_completions(
    prompt: str,
    *,
    base_url: str,
    model: str,
    api_key: str,
    auth_header: str,
    timeout: int,
) -> dict:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a careful maintenance engineer for Python web scrapers. "
                    "Return only JSON matching the requested schema. Prefer tiny, localized fixes. "
                    "If the safe fix requires broader design changes, mark major_change true and leave patch empty."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "scraper_fix",
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["confidence", "major_change", "summary", "patch"],
                    "properties": {
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "major_change": {"type": "boolean"},
                        "summary": {"type": "string"},
                        "patch": {"type": "string"},
                    },
                },
            },
        },
    }
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers[auth_header] = f"Bearer {api_key}"
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=data,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise SystemExit(f"Could not reach model API at {base_url}: {exc}") from exc
    content = result["choices"][0]["message"]["content"]
    return json.loads(content)


def call_lm_studio(prompt: str, *, base_url: str, model: str, timeout: int) -> dict:
    return call_chat_completions(
        prompt,
        base_url=base_url,
        model=model,
        api_key="lm-studio",
        auth_header="Authorization",
        timeout=timeout,
    )


def call_ollama(prompt: str, *, base_url: str, model: str, timeout: int) -> dict:
    return call_chat_completions(
        prompt,
        base_url=base_url,
        model=model,
        api_key="",
        auth_header="Authorization",
        timeout=timeout,
    )


def call_deepseek(prompt: str, *, api_key: str, model: str, timeout: int) -> dict:
    """DeepSeek API — OpenAI-compatible but only supports json_object, not json_schema."""
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a careful maintenance engineer for Python web scrapers. "
                    "Return ONLY a JSON object. Prefer tiny, localized fixes. "
                    "If the safe fix requires broader design changes, mark major_change true and leave patch empty."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    request = urllib.request.Request(
        "https://api.deepseek.com/v1/chat/completions",
        data=data,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise SystemExit(f"Could not reach DeepSeek API: {exc}") from exc
    content = result["choices"][0]["message"]["content"]
    cleaned = re.sub(r"^```(?:json)?\s*", "", content.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


def call_anthropic(prompt: str, *, api_key: str, model: str, timeout: int) -> dict:
    """Call Anthropic Messages API and return parsed JSON."""
    payload = {
        "model": model,
        "max_tokens": 4096,
        "system": (
            "You are a careful maintenance engineer for Python web scrapers. "
            "Return ONLY valid JSON matching the requested schema. Prefer tiny, localized fixes. "
            "If the safe fix requires broader design changes, mark major_change true and leave patch empty."
        ),
        "messages": [
            {
                "role": "user",
                "content": (
                    prompt
                    + "\n\nReturn your response as a single JSON object with exactly these keys: "
                    "confidence (number 0-1), major_change (boolean), summary (string), "
                    "patch (string containing a unified git diff, or empty string if major_change is true). "
                    "Do not wrap the JSON in markdown code blocks. Return ONLY the JSON object."
                ),
            }
        ],
        "temperature": 0.1,
    }
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    request = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=data,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise SystemExit(f"Could not reach Anthropic API: {exc}") from exc

    raw = result["content"][0]["text"].strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def call_model(prompt: str, args: argparse.Namespace) -> dict:
    if args.provider == "ollama":
        return call_ollama(
            prompt,
            base_url=args.ollama_base_url,
            model=args.model,
            timeout=args.timeout,
        )
    if args.provider == "deepseek":
        api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            raise SystemExit("DEEPSEEK_API_KEY is required for --provider deepseek")
        return call_deepseek(
            prompt,
            api_key=api_key,
            model=args.model,
            timeout=args.timeout,
        )
    if args.provider == "anthropic":
        api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise SystemExit("ANTHROPIC_API_KEY is required for --provider anthropic")
        return call_anthropic(
            prompt,
            api_key=api_key,
            model=args.model,
            timeout=args.timeout,
        )
    return call_lm_studio(prompt, base_url=args.lm_base_url, model=args.model, timeout=args.timeout)


def _extract_error_files(logs: str, city: str) -> list[str]:
    """Parse Python tracebacks from logs to find implicated source files."""
    files: set[str] = set()
    for match in re.finditer(r'File "([^"]+)", line (\d+)', logs):
        path = match.group(1)
        norm = re.sub(r"^.*?/" + re.escape(city) + r"/", city + "/", path)
        if norm.startswith(f"{city}/"):
            files.add(norm)
    return sorted(files)


def _read_source_files(file_paths: list[str], root: Path, max_bytes: int = 60000) -> str:
    """Read source files, newest-first, truncated to max_bytes total."""
    parts: list[str] = []
    total = 0
    for path in file_paths:
        full = root / path
        if not full.is_file():
            continue
        content = full.read_text(encoding="utf-8")
        if total + len(content) > max_bytes:
            remaining = max_bytes - total
            content = content[:remaining] + "\n# ... [truncated]"
        parts.append(f"=== {path} ===\n{content}")
        total += len(content)
        if total >= max_bytes:
            break
    return "\n\n".join(parts)


def build_prompt(issue: dict, city: str, logs: str, policy: dict) -> str:
    city_policy = policy["cities"][city]
    allowed = "\n".join(f"- {path}" for path in city_policy["allowed_paths"])
    blocked = "\n".join(f"- {path}" for path in city_policy["blocked_paths"])

    error_files = _extract_error_files(logs, city)
    main_path = f"{city}/main_scraper.py"
    if main_path not in error_files and (ROOT / main_path).is_file():
        error_files.append(main_path)
    source_code = _read_source_files(error_files, ROOT) if error_files else "(could not determine failing files)"

    return textwrap.dedent(
        f"""
        Fix this {city} cinema scraper failure if it is a small, safe maintenance change.

        Issue:
        {issue.get('title')}

        Issue body:
        {issue.get('body') or ''}

        Failing source code:
        {source_code}

        Recent workflow log excerpt (contains the actual error):
        {logs}

        Allowed paths:
        {allowed}

        Blocked paths:
        {blocked}

        Return a unified git diff in the patch field. The patch must only touch allowed paths.
        Common failure modes to check:
        - Website HTML structure changed → update CSS selectors or parsing logic
        - URL changed → update the request URL
        - New anti-bot protection → may need user-agent or header changes
        - Venue closed/renamed → remove or update the cinema module

        Set major_change true and patch empty if this requires a broad rewrite, workflow/secret changes,
        shared infrastructure changes, data-only changes, or human product judgment.
        """
    ).strip()


def changed_files_from_patch(patch: str) -> set[str]:
    files = set()
    for match in re.finditer(r"^diff --git a/(.*?) b/(.*?)$", patch, flags=re.MULTILINE):
        files.add(match.group(2))
    return files


def patch_line_count(patch: str) -> int:
    return sum(1 for line in patch.splitlines() if line.startswith(("+", "-")) and not line.startswith(("+++", "---")))


def policy_allows_patch(policy: dict, city: str, patch: str, confidence: float, major_change: bool) -> tuple[bool, str]:
    if major_change:
        return False, "model marked this as a major change"
    if confidence < float(policy["min_confidence"]):
        return False, f"confidence {confidence:.2f} below threshold"
    if patch_line_count(patch) > int(policy["max_patch_lines"]):
        return False, "patch is larger than policy allows"

    city_policy = policy["cities"][city]
    allowed = tuple(city_policy["allowed_paths"])
    blocked = tuple(city_policy["blocked_paths"])
    files = changed_files_from_patch(patch)
    if not files:
        return False, "patch did not contain changed files"
    for file_path in files:
        if file_path.startswith(blocked):
            return False, f"{file_path} is blocked"
        if not file_path.startswith(allowed):
            return False, f"{file_path} is outside allowed paths"
    return True, "allowed"


def apply_patch(patch: str) -> None:
    run(["git", "apply", "--check"], input_text=patch)
    run(["git", "apply"], input_text=patch)


def verify(city: str, policy: dict) -> None:
    for command in policy["cities"][city]["verify"]:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            shell=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"Verification failed: {command}\n{completed.stdout}")


def mark_major(issue: dict, policy: dict, reason: str) -> None:
    gh_text(["issue", "edit", str(issue["number"]), "--add-label", policy["labels"]["major"]], check=False)
    gh_text(["issue", "comment", str(issue["number"]), "--body", f"Auto-fix paused for human review: {reason}"], check=False)


def push_to_main(issue: dict, city: str, summary: str) -> None:
    """Commit fix and push directly to main."""
    run(["git", "checkout", "main"])
    run(["git", "pull", "--rebase", "-X", "theirs", "origin", "main"])
    run(["git", "add", "."])
    run(["git", "commit", "-m", f"Auto-fix {city} scraper issue #{issue['number']}\n\n{summary}"])
    run(["git", "push", "origin", "main"])
    gh_text(
        ["issue", "close", str(issue["number"]), "--reason", "resolved"],
        check=False,
    )
    gh_text(
        [
            "issue",
            "comment",
            str(issue["number"]),
            "--body",
            f"Fixed and pushed to main.\n\n**Summary:** {summary}",
        ],
        check=False,
    )


def process_issue(issue: dict, args: argparse.Namespace, policy: dict) -> dict:
    city = infer_city(issue, policy)
    if not city:
        mark_major(issue, policy, "could not infer city from issue labels/body")
        return {
            "issue": issue["number"],
            "title": issue.get("title", ""),
            "status": "paused",
            "summary": "Could not infer city from issue labels/body.",
            "url": issue.get("url", ""),
        }

    run_id = extract_run_id(issue.get("body") or "")
    logs = get_run_logs(run_id, args.log_chars)
    prompt = build_prompt(issue, city, logs, policy)
    response = call_model(prompt, args)
    patch = response.get("patch") or ""
    confidence = float(response.get("confidence") or 0)
    major_change = bool(response.get("major_change"))
    summary = str(response.get("summary") or "No summary provided.")

    allowed, reason = policy_allows_patch(policy, city, patch, confidence, major_change)
    if not allowed:
        mark_major(issue, policy, reason)
        return {
            "issue": issue["number"],
            "title": issue.get("title", ""),
            "city": city,
            "status": "paused",
            "summary": reason,
            "url": issue.get("url", ""),
        }

    apply_patch(patch)
    verify(city, policy)

    if args.dry_run:
        print(f"Dry run succeeded for issue #{issue['number']}")
        print(summary)
        return {
            "issue": issue["number"],
            "title": issue.get("title", ""),
            "city": city,
            "status": "dry-run",
            "summary": summary,
            "url": issue.get("url", ""),
        }

    push_to_main(issue, city, summary)
    print(f"Pushed fix for #{issue['number']} ({city}) to main")
    return {
        "issue": issue["number"],
        "title": issue.get("title", ""),
        "city": city,
        "status": "applied",
        "summary": summary,
        "url": issue.get("url", ""),
    }


def post_weekly_summary(results: list[dict], *, dry_run: bool = False) -> None:
    """Post a single weekly summary as a GitHub issue — no emails, no per-fix PRs."""
    if not results:
        return

    applied = [r for r in results if r.get("status") == "applied"]
    paused = [r for r in results if r.get("status") == "paused"]
    errors = [r for r in results if r.get("status") == "error"]
    dry_runs = [r for r in results if r.get("status") == "dry-run"]

    if not (applied or paused or errors):
        return

    now = datetime.now(timezone.utc)
    week_key = current_week_key()
    mode = "dry run" if dry_run else "applied directly to main"

    lines = [
        f"## Auto-fix weekly summary — {week_key}",
        "",
        f"**Run time:** {now.strftime('%Y-%m-%d %H:%M:%S')} UTC",
        f"**Mode:** {mode}",
        "",
        f"| Status | Count |",
        f"|--------|-------|",
        f"| ✅ Applied | {len(applied)} |",
        f"| ⏸️ Paused for review | {len(paused)} |",
        f"| ❌ Errors | {len(errors)} |",
    ]
    if dry_runs:
        lines.append(f"| 🔍 Dry-run | {len(dry_runs)} |")

    def _append_group(title: str, emoji: str, items: list[dict]) -> None:
        if not items:
            return
        lines.extend(["", f"### {emoji} {title}"])
        for item in items:
            city = item.get("city", "?").title()
            lines.append(f"- **#{item.get('issue')}** ({city}): {item.get('title', '')}")
            if item.get("summary"):
                lines.append(f"  > {item['summary']}")

    _append_group("Applied fixes", "✅", applied)
    _append_group("Paused — needs human review", "⏸️", paused)
    _append_group("Errors", "❌", errors)

    summary_label = "auto-fix-summary"
    gh_text(["label", "create", summary_label, "--color", "0e8a16"], check=False)

    existing = gh_text(
        [
            "issue", "list", "--state", "open", "--label", summary_label,
            "--search", f'"Auto-fix weekly summary — {week_key}" in:title',
            "--json", "number", "--jq", ".[0].number // empty",
        ]
    ).strip()

    body = "\n".join(lines)
    if existing:
        gh_text(["issue", "comment", existing, "--body", body])
        print(f"Appended to existing weekly summary #{existing}")
    else:
        gh_text([
            "issue", "create",
            "--title", f"Auto-fix weekly summary — {week_key}",
            "--body", body,
            "--label", summary_label,
        ])
        print(f"Created weekly summary issue for {week_key}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Attempt safe scraper auto-fixes with a local chat-completions model API.")
    parser.add_argument("--provider", choices=["ollama", "lm-studio", "deepseek", "anthropic"], default=os.environ.get("AUTOFIX_MODEL_PROVIDER", "ollama"))
    parser.add_argument("--model", default=os.environ.get("AUTOFIX_MODEL", os.environ.get("OLLAMA_MODEL", os.environ.get("LM_STUDIO_MODEL", "qwen3:14b"))))
    parser.add_argument("--ollama-base-url", default=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"))
    parser.add_argument("--lm-base-url", default=os.environ.get("LM_STUDIO_BASE_URL", "http://localhost:1234/v1"))
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--log-chars", type=int, default=30000)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--auto-merge", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--weekly-summary", action="store_true", help="Post a single weekly-summary GitHub issue instead of per-fix PRs")
    parser.add_argument("--email-summary", action="store_true")
    parser.add_argument("--state-file", type=Path, default=STATE_PATH)
    parser.add_argument("--api-key", default="", help="API key for cloud providers (DeepSeek, Anthropic)")
    parser.add_argument("--ci", action="store_true", help="Run in CI mode: skip weekly-run gate, push directly to main")
    parser.add_argument("--force", action="store_true", help="Run even if this week's successful run has already completed.")
    parser.add_argument("--skip-health-monitor", action="store_true", help="Skip source/Instagram health checks before auto-fixing issues.")
    parser.add_argument("--health-sample-size", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if should_skip_weekly_run(args):
        print(f"Auto-fix already completed successfully for {current_week_key()}; skipping until next week.")
        return 0

    policy = load_policy()
    ensure_clean_worktree()
    run(["git", "fetch", "origin", "main"])

    # Work directly on main — fixes are pushed as they're applied
    run(["git", "checkout", "main"])
    run(["git", "pull", "--rebase", "-X", "theirs", "origin", "main"])

    results: list[dict] = []
    try:
        run_health_monitor(args)
        issues = list_candidate_issues(policy, args.limit)
        for issue in issues:
            try:
                results.append(process_issue(issue, args, policy))
            except Exception as exc:
                results.append(
                    {
                        "issue": issue.get("number"),
                        "title": issue.get("title", ""),
                        "status": "error",
                        "summary": str(exc),
                        "url": issue.get("url", ""),
                    }
                )
                print(f"Error processing issue #{issue.get('number')}: {exc}", file=sys.stderr)
                # Reset to main for the next issue
                run(["git", "checkout", "--", "."], check=False)
                run(["git", "checkout", "main"], check=False)
                run(["git", "pull", "--rebase", "-X", "theirs", "origin", "main"], check=False)
    finally:
        run(["git", "checkout", "main"], check=False)

    if args.weekly_summary:
        post_weekly_summary(results, dry_run=args.dry_run)
    elif args.email_summary:
        # Legacy email path — kept for local use
        _send_legacy_email_summary(results, dry_run=args.dry_run)
    mark_weekly_run_success(args)
    return 0


def _send_legacy_email_summary(results: list[dict], *, dry_run: bool = False) -> None:
    """Legacy email summary — only used when --email-summary is passed (local dev)."""
    smtp_email = os.environ.get("SMTP_EMAIL", "").strip()
    smtp_password = os.environ.get("SMTP_PASSWORD", "").strip()
    recipient = os.environ.get("ALERT_RECIPIENT_EMAIL", "").strip() or smtp_email
    smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com").strip()
    smtp_port = int(os.environ.get("SMTP_PORT") or "587")

    if not smtp_email or not smtp_password or not recipient:
        print("Skipping auto-fix summary email: missing SMTP credentials.")
        return

    applied = [r for r in results if r.get("status") == "applied"]
    paused = [r for r in results if r.get("status") == "paused"]
    errors = [r for r in results if r.get("status") == "error"]

    lines = [
        "Cinema scraper auto-fix summary",
        "",
        f"Run time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Mode: {'dry run' if dry_run else 'applied to main'}",
        f"Applied: {len(applied)}",
        f"Paused for review: {len(paused)}",
        f"Errors: {len(errors)}",
    ]

    msg = EmailMessage()
    msg["From"] = smtp_email
    msg["To"] = recipient
    msg["Subject"] = f"Cinema scraper auto-fix: {len(applied)} applied, {len(paused)} paused"
    msg.set_content("\n".join(lines), charset="utf-8")

    with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as server:
        server.starttls()
        server.login(smtp_email, smtp_password)
        server.send_message(msg)

    print(f"Sent auto-fix summary email to {recipient}")


if __name__ == "__main__":
    raise SystemExit(main())
