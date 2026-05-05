"""Outbound email delivery service."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path

from app.core.config import Settings, get_settings
from app.utils.time import utcnow


logger = logging.getLogger(__name__)


class EmailService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def send_verification_code(self, *, email: str, code: str, purpose: str, expires_in_seconds: int) -> None:
        provider = str(self.settings.email_provider or "console").strip().lower()
        if provider == "smtp":
            self._send_smtp(email=email, code=code, purpose=purpose, expires_in_seconds=expires_in_seconds)
            return
        if provider == "file":
            self._write_file(email=email, code=code, purpose=purpose, expires_in_seconds=expires_in_seconds)
            return
        if provider == "console":
            logger.info(
                "Email verification code issued provider=console email=%s purpose=%s code=%s expires_in=%ss",
                email,
                purpose,
                code,
                expires_in_seconds,
            )
            return
        raise RuntimeError(f"unsupported email provider: {provider}")

    def _send_smtp(self, *, email: str, code: str, purpose: str, expires_in_seconds: int) -> None:
        if not self.settings.smtp_host:
            raise RuntimeError("SMTP_HOST is required when EMAIL_PROVIDER=smtp")

        message = EmailMessage()
        message["From"] = self.settings.email_from
        message["To"] = email
        message["Subject"] = "AssistIM email verification code"
        minutes = max(1, int(expires_in_seconds // 60))
        message.set_content(
            "\n".join(
                [
                    f"Your AssistIM {purpose} verification code is: {code}",
                    f"This code expires in {minutes} minute(s).",
                    "If you did not request this code, ignore this email.",
                ]
            )
        )

        with smtplib.SMTP(self.settings.smtp_host, int(self.settings.smtp_port), timeout=15) as smtp:
            if self.settings.smtp_use_tls:
                smtp.starttls()
            if self.settings.smtp_username:
                smtp.login(self.settings.smtp_username, self.settings.smtp_password)
            smtp.send_message(message)

    def _write_file(self, *, email: str, code: str, purpose: str, expires_in_seconds: int) -> None:
        target = Path(self.settings.email_verification_file_path or Path(self.settings.log_dir) / "email_verification_codes.log")
        target.parent.mkdir(parents=True, exist_ok=True)
        line = (
            f"{utcnow().isoformat()} email={email} purpose={purpose} "
            f"code={code} expires_in={expires_in_seconds}s\n"
        )
        with target.open("a", encoding="utf-8") as handle:
            handle.write(line)
