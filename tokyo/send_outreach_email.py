#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import smtplib
import ssl
import sys
import time
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_RECIPIENTS_FILE = BASE_DIR / "data" / "outreach_recipients.json"
DEFAULT_TEMPLATE_FILE = BASE_DIR / "data" / "outreach_email_ja.txt"
DEFAULT_SUBJECT = "東京の上映情報サイトを作りました"
DEFAULT_FROM_NAME = os.environ.get("OUTREACH_FROM_NAME", "Leo")
DEFAULT_SITE_URL = "https://cinematokyo.com/"
DEFAULT_IG_URL = "https://www.instagram.com/tokyominitheater/"
EXCLUDED_CINEMAS = {
    "シアター・イメージフォーラム",
    "Stranger (ストレンジャー)",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send Tokyo cinema outreach emails.")
    parser.add_argument(
        "--recipients-file",
        type=Path,
        default=DEFAULT_RECIPIENTS_FILE,
        help="Path to the JSON recipient list.",
    )
    parser.add_argument(
        "--template-file",
        type=Path,
        default=DEFAULT_TEMPLATE_FILE,
        help="Path to the Japanese plain-text email template.",
    )
    parser.add_argument(
        "--subject",
        default=DEFAULT_SUBJECT,
        help="Email subject line.",
    )
    parser.add_argument(
        "--site-url",
        default=DEFAULT_SITE_URL,
        help="Website URL to include in the message.",
    )
    parser.add_argument(
        "--instagram-url",
        default=DEFAULT_IG_URL,
        help="Instagram URL to include in the message.",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=20.0,
        help="Delay between messages when sending.",
    )
    parser.add_argument(
        "--max-recipients",
        type=int,
        default=0,
        help="Limit the number of recipients sent to. 0 means all.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the final recipient list and message preview without sending.",
    )
    return parser.parse_args()


def load_recipients(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, list):
        raise ValueError("Recipient file must contain a JSON array.")

    recipients: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        cinema_name = str(entry.get("cinema_name", "")).strip()
        email = str(entry.get("email", "")).strip()
        source = str(entry.get("source", "")).strip()

        if not cinema_name or not email:
            continue
        if cinema_name in EXCLUDED_CINEMAS:
            continue

        recipients.append(
            {
                "cinema_name": cinema_name,
                "email": email,
                "source": source,
            }
        )

    return recipients


def load_template(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def build_message_text(template: str, *, site_url: str, instagram_url: str) -> str:
    return template.format(site_url=site_url, instagram_url=instagram_url)


def build_email(
    *,
    sender_email: str,
    cinema_name: str,
    recipient_email: str,
    subject: str,
    body: str,
    from_name: str,
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((from_name, sender_email))
    msg["To"] = recipient_email
    msg["Subject"] = subject
    msg["Reply-To"] = sender_email
    msg.set_content(f"{cinema_name}のみなさま\n\n{body}", charset="utf-8")
    return msg


def env_or_default(name: str, default: str) -> str:
    value = os.environ.get(name, "")
    value = value.strip()
    return value if value else default


def send_message(
    msg: EmailMessage,
    *,
    smtp_email: str,
    smtp_password: str,
    smtp_server: str,
    smtp_port: int,
) -> None:
    if smtp_port == 465:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(smtp_server, smtp_port, context=context, timeout=30) as server:
            server.login(smtp_email, smtp_password)
            server.send_message(msg)
        return

    context = ssl.create_default_context()
    with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as server:
        server.ehlo()
        server.starttls(context=context)
        server.ehlo()
        server.login(smtp_email, smtp_password)
        server.send_message(msg)


def main() -> int:
    args = parse_args()

    recipients = load_recipients(args.recipients_file)
    if args.max_recipients and args.max_recipients > 0:
        recipients = recipients[: args.max_recipients]

    template = load_template(args.template_file)
    body = build_message_text(
        template,
        site_url=args.site_url,
        instagram_url=args.instagram_url,
    )

    if args.dry_run:
        print(f"Dry run: {len(recipients)} recipient(s) after exclusions.")
        for idx, recipient in enumerate(recipients, start=1):
            print(f"{idx:02d}. {recipient['cinema_name']} <{recipient['email']}>")
            if recipient.get("source"):
                print(f"    source: {recipient['source']}")
        print()
        print("Message preview:")
        print("-" * 60)
        print(body)
        print("-" * 60)
        return 0

    smtp_email = env_or_default("SMTP_EMAIL", "")
    smtp_password = env_or_default("SMTP_PASSWORD", "")
    smtp_server = env_or_default("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(env_or_default("SMTP_PORT", "587"))

    if not smtp_email or not smtp_password:
        print("Missing SMTP_EMAIL or SMTP_PASSWORD.", file=sys.stderr)
        return 1

    if not recipients:
        print("No recipients available after exclusions.", file=sys.stderr)
        return 1

    failures: list[tuple[str, str]] = []

    for idx, recipient in enumerate(recipients, start=1):
        cinema_name = recipient["cinema_name"]
        recipient_email = recipient["email"]
        msg = build_email(
            sender_email=smtp_email,
            cinema_name=cinema_name,
            recipient_email=recipient_email,
            subject=args.subject,
            body=body,
            from_name=DEFAULT_FROM_NAME,
        )

        print(f"[{idx}/{len(recipients)}] Sending to {cinema_name} <{recipient_email}>")
        try:
            send_message(
                msg,
                smtp_email=smtp_email,
                smtp_password=smtp_password,
                smtp_server=smtp_server,
                smtp_port=smtp_port,
            )
        except Exception as exc:  # pragma: no cover - surfaced in workflow logs
            failures.append((cinema_name, str(exc)))
            print(f"  failed: {exc}", file=sys.stderr)

        if idx < len(recipients) and args.delay_seconds > 0:
            time.sleep(args.delay_seconds)

    if failures:
        print("\nCompleted with failures:", file=sys.stderr)
        for cinema_name, error in failures:
            print(f"- {cinema_name}: {error}", file=sys.stderr)
        return 1

    print(f"Sent {len(recipients)} email(s) successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
