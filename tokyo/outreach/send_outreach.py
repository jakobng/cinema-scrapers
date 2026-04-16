"""
send_outreach.py
Sends a friendly outreach email (in Japanese) to Tokyo cinema venues
featured on the site.

Required environment variables:
    SMTP_EMAIL          - Sender Gmail address
    SMTP_PASSWORD       - Gmail App Password
    WEBSITE_URL         - URL of the cinema listings page
    IG_HANDLE           - Instagram handle (e.g. @tokyocinemascope)
    SENDER_NAME         - Name to sign off the email with

Optional:
    DRY_RUN             - Set to "1" to print emails without sending
"""

import json
import os
import smtplib
import ssl
import time
from email.message import EmailMessage
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 465))
SENDER_EMAIL = os.environ.get("SMTP_EMAIL")
SENDER_PASSWORD = os.environ.get("SMTP_PASSWORD")

WEBSITE_URL = os.environ.get("WEBSITE_URL", "https://www.leonelki.com/tokyo")
IG_HANDLE = os.environ.get("IG_HANDLE", "@YOUR_IG_HANDLE")
SENDER_NAME = os.environ.get("SENDER_NAME", "Jakob")

DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"

EMAILS_FILE = Path(__file__).parent / "cinema_emails.json"

# Delay between sends to avoid Gmail rate limits (seconds)
SEND_DELAY = 3


# ---------------------------------------------------------------------------
# Email template
# ---------------------------------------------------------------------------

SUBJECT = "東京のミニシアター情報サイトを作りました！"

BODY_TEMPLATE = """\
はじめまして！

突然のご連絡、失礼します。映画が大好きで、東京のミニシアターによく足を運んでいます。

毎回、各映画館のサイトをひとつひとつ回って上映情報をチェックするのが大変で…それなら自分でまとめサイトを作ってしまおう！と思い立ち、東京のミニシアターの上映情報をまとめて一覧で見られるページを作りました。

{cinema_name_jp}さんの情報もしっかり載せています！

🌐 サイト: {website_url}
📸 Instagram: {ig_handle}

Instagramでは毎日その日の上映情報をポストしています。ミニシアターをもっと多くの人に知ってもらえたらいいな、という気持ちで作りました。よければぜひ見てみてください！

何かご意見やご要望があれば、お気軽にご連絡ください。

よろしくお願いします！
{sender_name}
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_cinemas():
    with open(EMAILS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return [c for c in data["cinemas"] if c.get("email")]


def build_message(cinema: dict) -> EmailMessage:
    body = BODY_TEMPLATE.format(
        cinema_name_jp=cinema["name_jp"],
        website_url=WEBSITE_URL,
        ig_handle=IG_HANDLE,
        sender_name=SENDER_NAME,
    )
    msg = EmailMessage()
    msg["Subject"] = SUBJECT
    msg["From"] = SENDER_EMAIL
    msg["To"] = cinema["email"]
    msg.set_content(body)
    return msg


def send_all():
    cinemas = load_cinemas()
    print(f"{'[DRY RUN] ' if DRY_RUN else ''}Sending to {len(cinemas)} cinema(s)...\n")

    if not DRY_RUN and not (SENDER_EMAIL and SENDER_PASSWORD):
        raise RuntimeError("SMTP_EMAIL and SMTP_PASSWORD must be set.")

    context = ssl.create_default_context()

    sent = 0
    failed = 0

    for cinema in cinemas:
        msg = build_message(cinema)
        print(f"  → {cinema['name_jp']} <{cinema['email']}>")

        if DRY_RUN:
            print("    [dry run — not sent]")
            continue

        try:
            with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=context) as server:
                server.login(SENDER_EMAIL, SENDER_PASSWORD)
                server.send_message(msg)
            print("    ✅ Sent")
            sent += 1
        except Exception as e:
            print(f"    ❌ Failed: {e}")
            failed += 1

        time.sleep(SEND_DELAY)

    print(f"\nDone. Sent: {sent}, Failed: {failed}, Skipped (dry run): {len(cinemas) - sent - failed}")


if __name__ == "__main__":
    send_all()
