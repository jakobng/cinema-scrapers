#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
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


def call_model(prompt: str, args: argparse.Namespace) -> dict:
    if args.provider == "ollama":
        return call_ollama(
            prompt,
            base_url=args.ollama_base_url,
            model=args.model,
            timeout=args.timeout,
        )
    return call_lm_studio(prompt, base_url=args.lm_base_url, model=args.model, timeout=args.timeout)


def build_prompt(issue: dict, city: str, logs: str, policy: dict) -> str:
    city_policy = policy["cities"][city]
    allowed = "\n".join(f"- {path}" for path in city_policy["allowed_paths"])
    blocked = "\n".join(f"- {path}" for path in city_policy["blocked_paths"])
    return textwrap.dedent(
        f"""
        Fix this {city} cinema scraper failure if it is a small, safe maintenance change.

        Issue:
        {issue.get('title')}

        Issue body:
        {issue.get('body') or ''}

        Recent workflow log excerpt:
        {logs}

        Allowed paths:
        {allowed}

        Blocked paths:
        {blocked}

        Return a unified git diff in the patch field. The patch must only touch allowed paths.
        Set major_change true and patch empty if this appears to require a broad rewrite, workflow/secret changes,
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


def open_pr(issue: dict, city: str, summary: str, auto_merge: bool, policy_allowed: bool) -> str:
    title = f"Auto-fix {city} scraper issue #{issue['number']}"
    body = textwrap.dedent(
        f"""
        Automated scraper maintenance for #{issue['number']}.

        Summary:
        {summary}

        Auto-merge policy result: {'allowed' if policy_allowed else 'manual review required'}
        """
    ).strip()
    pr_url = gh_text(["pr", "create", "--title", title, "--body", body]).strip()
    gh_text(["issue", "comment", str(issue["number"]), "--body", f"Opened auto-fix PR: {pr_url}"])
    if auto_merge and policy_allowed:
        gh_text(["pr", "merge", "--auto", "--squash", "--delete-branch"], check=False)
    return pr_url


def mark_major(issue: dict, policy: dict, reason: str) -> None:
    gh_text(["issue", "edit", str(issue["number"]), "--add-label", policy["labels"]["major"]], check=False)
    gh_text(["issue", "comment", str(issue["number"]), "--body", f"Auto-fix paused for human review: {reason}"], check=False)


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

    branch = f"codex/autofix-{city}-{issue['number']}"
    run(["git", "checkout", "-B", branch, "origin/main"])
    apply_patch(patch)
    verify(city, policy)

    if args.dry_run:
        print(f"Dry run succeeded for issue #{issue['number']} on {branch}")
        print(summary)
        return {
            "issue": issue["number"],
            "title": issue.get("title", ""),
            "city": city,
            "status": "dry-run",
            "summary": summary,
            "branch": branch,
            "url": issue.get("url", ""),
        }

    run(["git", "add", "."])
    run(["git", "commit", "-m", f"Auto-fix {city} scraper issue #{issue['number']}"])
    run(["git", "push", "-u", "origin", branch])
    pr_url = open_pr(issue, city, summary, args.auto_merge, allowed)
    gh_text(["issue", "edit", str(issue["number"]), "--add-label", policy["labels"]["done"]], check=False)
    print(f"Opened {pr_url}")
    return {
        "issue": issue["number"],
        "title": issue.get("title", ""),
        "city": city,
        "status": "pr-opened",
        "summary": summary,
        "branch": branch,
        "pr_url": pr_url,
        "url": issue.get("url", ""),
    }


def send_summary_email(results: list[dict], *, dry_run: bool = False) -> None:
    smtp_email = os.environ.get("SMTP_EMAIL", "").strip()
    smtp_password = os.environ.get("SMTP_PASSWORD", "").strip()
    recipient = os.environ.get("ALERT_RECIPIENT_EMAIL", "").strip() or smtp_email
    smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com").strip()
    smtp_port = int(os.environ.get("SMTP_PORT") or "587")

    if not smtp_email or not smtp_password or not recipient:
        print("Skipping auto-fix summary email: missing SMTP_EMAIL, SMTP_PASSWORD, or recipient.")
        return

    opened = [result for result in results if result.get("status") == "pr-opened"]
    paused = [result for result in results if result.get("status") == "paused"]
    errors = [result for result in results if result.get("status") == "error"]
    dry_runs = [result for result in results if result.get("status") == "dry-run"]

    lines = [
        "Cinema scraper auto-fix weekly summary",
        "",
        f"Run time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Mode: {'dry run' if dry_run else 'PR only'}",
        f"PRs opened: {len(opened)}",
        f"Paused for review: {len(paused)}",
        f"Errors: {len(errors)}",
    ]
    if dry_runs:
        lines.append(f"Dry-run candidates: {len(dry_runs)}")

    def append_result_group(title: str, items: list[dict]) -> None:
        if not items:
            return
        lines.extend(["", title])
        for item in items:
            lines.append(f"- #{item.get('issue')} {item.get('city', '').title()} {item.get('title', '')}".strip())
            if item.get("summary"):
                lines.append(f"  Summary: {item['summary']}")
            if item.get("pr_url"):
                lines.append(f"  Review and merge: {item['pr_url']}")
            elif item.get("url"):
                lines.append(f"  Issue: {item['url']}")

    append_result_group("Opened PRs", opened)
    append_result_group("Paused items", paused)
    append_result_group("Errors", errors)
    append_result_group("Dry-run items", dry_runs)

    if not results:
        lines.extend(["", "No open auto-fix candidate issues were found."])

    msg = EmailMessage()
    msg["From"] = smtp_email
    msg["To"] = recipient
    msg["Subject"] = f"Cinema scraper auto-fix summary: {len(opened)} PR(s), {len(paused)} paused"
    msg.set_content("\n".join(lines), charset="utf-8")

    with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as server:
        server.starttls()
        server.login(smtp_email, smtp_password)
        server.send_message(msg)

    print(f"Sent auto-fix summary email to {recipient}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Attempt safe scraper auto-fixes with a local chat-completions model API.")
    parser.add_argument("--provider", choices=["ollama", "lm-studio"], default=os.environ.get("AUTOFIX_MODEL_PROVIDER", "ollama"))
    parser.add_argument("--model", default=os.environ.get("AUTOFIX_MODEL", os.environ.get("OLLAMA_MODEL", os.environ.get("LM_STUDIO_MODEL", "qwen2.5-coder:14b"))))
    parser.add_argument("--ollama-base-url", default=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"))
    parser.add_argument("--lm-base-url", default=os.environ.get("LM_STUDIO_BASE_URL", "http://localhost:1234/v1"))
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--log-chars", type=int, default=30000)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--auto-merge", action="store_true")
    parser.add_argument("--email-summary", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    policy = load_policy()
    starting_branch = current_branch()
    ensure_clean_worktree()
    run(["git", "fetch", "origin", "main"])

    try:
        issues = list_candidate_issues(policy, args.limit)
        results: list[dict] = []
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
        if args.email_summary:
            send_summary_email(results, dry_run=args.dry_run)
    finally:
        run(["git", "checkout", starting_branch], check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
