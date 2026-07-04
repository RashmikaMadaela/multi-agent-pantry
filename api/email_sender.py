"""
api/email_sender.py

Sends a drafted restock email via Gmail SMTP using an App Password.
No third-party library required — uses Python's built-in smtplib.

SETUP (one-time):
    1. Enable 2-Step Verification on your Google account.
    2. Go to Google Account → Security → App Passwords.
    3. Create an App Password named "Pantry App".
    4. Add to .env:
         GMAIL_SENDER=you@gmail.com
         GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx

SECURITY:
    Credentials are read exclusively from environment variables.
    Never hardcoded, never logged.
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

log = logging.getLogger("email_sender")

GMAIL_SMTP_HOST = "smtp.gmail.com"
GMAIL_SMTP_PORT = 587


def send_restock_email(
    *,
    to_address: str,
    subject: str,
    body: str,
) -> None:
    """
    Sends a restock email from the configured Gmail account to the supplier.

    Args:
        to_address: Supplier's email address (from the DB).
        subject:    Email subject line.
        body:       The AI-drafted email body (may have been edited by user).

    Raises:
        EnvironmentError:   If GMAIL_SENDER or GMAIL_APP_PASSWORD are not set.
        smtplib.SMTPException: If the SMTP connection or send fails.
    """
    sender = os.environ.get("GMAIL_SENDER", "").strip()
    app_password = os.environ.get("GMAIL_APP_PASSWORD", "").strip()

    if not sender or not app_password:
        raise EnvironmentError(
            "GMAIL_SENDER and GMAIL_APP_PASSWORD must be set in .env to send emails. "
            "See api/email_sender.py for setup instructions."
        )

    # Build the MIME message
    msg = MIMEMultipart("alternative")
    msg["From"] = sender
    msg["To"] = to_address
    msg["Subject"] = subject

    # Plain text body (works in all email clients)
    msg.attach(MIMEText(body, "plain"))

    log.info("Connecting to Gmail SMTP: %s:%d", GMAIL_SMTP_HOST, GMAIL_SMTP_PORT)

    with smtplib.SMTP(GMAIL_SMTP_HOST, GMAIL_SMTP_PORT) as server:
        server.ehlo()
        server.starttls()  # Upgrade to TLS — always required for Gmail
        server.ehlo()
        server.login(sender, app_password)
        server.sendmail(sender, to_address, msg.as_string())

    log.info("✅ Email sent to %s | Subject: %s", to_address, subject)
