"""Email verification code issuance and validation."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import AppError, ErrorCode
from app.models.email_verification import EmailVerificationCode
from app.repositories.user_repo import UserRepository
from app.services.email_service import EmailService
from app.utils.time import utcnow


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
REGISTER_PURPOSE = "register"
PASSWORD_RESET_PURPOSE = "password_reset"


def normalize_email_address(value: str) -> str:
    email = str(value or "").strip().lower()
    if not email or len(email) > 255 or not EMAIL_PATTERN.fullmatch(email):
        raise AppError(ErrorCode.INVALID_REQUEST, "invalid email format", 400)
    return email


class EmailVerificationService:
    def __init__(
        self,
        db: Session,
        settings: Settings | None = None,
        email_service: EmailService | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.email_service = email_service or EmailService(self.settings)
        self.users = UserRepository(db)

    def send_register_code(self, email: str, *, request_ip: str = "") -> dict[str, object]:
        normalized_email = normalize_email_address(email)
        if self.users.get_by_email(normalized_email) is not None:
            raise AppError(ErrorCode.USER_EXISTS, "email already registered", 409)
        return self._issue_code(normalized_email, REGISTER_PURPOSE, request_ip=request_ip)

    def send_password_reset_code(self, email: str, *, request_ip: str = "") -> dict[str, object]:
        normalized_email = normalize_email_address(email)
        user = self.users.get_by_email(normalized_email)
        if user is None:
            return self._generic_send_payload(normalized_email, PASSWORD_RESET_PURPOSE)

        return self._issue_code(normalized_email, PASSWORD_RESET_PURPOSE, request_ip=request_ip)

    def _issue_code(self, normalized_email: str, purpose: str, *, request_ip: str = "") -> dict[str, object]:
        now = utcnow()
        cooldown_seconds = max(0, int(self.settings.email_verification_resend_cooldown_seconds or 0))
        if cooldown_seconds:
            cutoff = now - timedelta(seconds=cooldown_seconds)
            recent = self.db.execute(
                select(EmailVerificationCode)
                .where(
                    EmailVerificationCode.email == normalized_email,
                    EmailVerificationCode.purpose == purpose,
                    EmailVerificationCode.consumed_at.is_(None),
                    EmailVerificationCode.created_at >= cutoff,
                )
                .order_by(EmailVerificationCode.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if recent is not None:
                raise AppError(ErrorCode.RATE_LIMITED, "email verification code recently sent", 429)

        ttl_seconds = max(60, int(self.settings.email_verification_ttl_seconds or 600))
        code = self._generate_code()
        record = EmailVerificationCode(
            email=normalized_email,
            purpose=purpose,
            code_hash=self._hash_code(normalized_email, purpose, code),
            expires_at=now + timedelta(seconds=ttl_seconds),
            request_ip=str(request_ip or "")[:64],
        )
        try:
            self.db.add(record)
            self.db.flush()
            self.email_service.send_verification_code(
                email=normalized_email,
                code=code,
                purpose=purpose,
                expires_in_seconds=ttl_seconds,
            )
            self.db.commit()
            self.db.refresh(record)
        except Exception:
            self.db.rollback()
            raise

        payload: dict[str, object] = {
            "sent": True,
            "email": normalized_email,
            "purpose": purpose,
            "expires_in": ttl_seconds,
            "cooldown_seconds": cooldown_seconds,
        }
        if bool(self.settings.email_verification_expose_code):
            payload["debug_code"] = code
        return payload

    def _generic_send_payload(self, normalized_email: str, purpose: str) -> dict[str, object]:
        return {
            "sent": True,
            "email": normalized_email,
            "purpose": purpose,
            "expires_in": max(60, int(self.settings.email_verification_ttl_seconds or 600)),
            "cooldown_seconds": max(0, int(self.settings.email_verification_resend_cooldown_seconds or 0)),
        }

    def consume_register_code(
        self,
        email: str,
        code: str,
        *,
        commit: bool = True,
        commit_failed_attempt: bool = True,
    ) -> str:
        return self._consume_code(
            email,
            code,
            purpose=REGISTER_PURPOSE,
            commit=commit,
            commit_failed_attempt=commit_failed_attempt,
        )

    def consume_password_reset_code(
        self,
        email: str,
        code: str,
        *,
        commit: bool = True,
        commit_failed_attempt: bool = True,
    ) -> str:
        return self._consume_code(
            email,
            code,
            purpose=PASSWORD_RESET_PURPOSE,
            commit=commit,
            commit_failed_attempt=commit_failed_attempt,
        )

    def _consume_code(
        self,
        email: str,
        code: str,
        *,
        purpose: str,
        commit: bool,
        commit_failed_attempt: bool,
    ) -> str:
        normalized_email = normalize_email_address(email)
        normalized_code = str(code or "").strip()
        if len(normalized_code) != 6 or not normalized_code.isdigit():
            raise AppError(ErrorCode.INVALID_REQUEST, "invalid email verification code", 400)
        now = utcnow()
        record = self.db.execute(
            select(EmailVerificationCode)
            .where(
                EmailVerificationCode.email == normalized_email,
                EmailVerificationCode.purpose == purpose,
                EmailVerificationCode.consumed_at.is_(None),
                EmailVerificationCode.expires_at > now,
            )
            .order_by(EmailVerificationCode.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if record is None:
            raise AppError(ErrorCode.INVALID_REQUEST, "invalid email verification code", 400)

        max_attempts = max(1, int(self.settings.email_verification_max_attempts or 5))
        if int(record.attempt_count or 0) >= max_attempts:
            raise AppError(ErrorCode.INVALID_REQUEST, "invalid email verification code", 400)

        expected_hash = self._hash_code(normalized_email, purpose, normalized_code)
        if not hmac.compare_digest(str(record.code_hash or ""), expected_hash):
            record.attempt_count = int(record.attempt_count or 0) + 1
            self.db.add(record)
            self.db.flush()
            if commit or commit_failed_attempt:
                self.db.commit()
            raise AppError(ErrorCode.INVALID_REQUEST, "invalid email verification code", 400)

        record.consumed_at = now
        self.db.add(record)
        self.db.flush()
        if commit:
            self.db.commit()
        return normalized_email

    @staticmethod
    def _generate_code() -> str:
        return f"{secrets.randbelow(1_000_000):06d}"

    def _hash_code(self, email: str, purpose: str, code: str) -> str:
        payload = f"{purpose}:{email}:{code}".encode("utf-8")
        return hmac.new(self.settings.secret_key.encode("utf-8"), payload, hashlib.sha256).hexdigest()
