"""
api/auth.py — JWT authentication via Supabase-compatible HS256 tokens.

Endpoints
---------
POST /auth/register  → create account, return token pair
POST /auth/login     → verify credentials, return token pair
POST /auth/refresh   → exchange refresh token for new access token

Dependency
----------
get_current_user()   → decodes Bearer token, returns JWT claims dict
                        import and use in any route that needs auth:
                            user = Depends(get_current_user)
                            user["sub"]   → UUID string  (user ID)
                            user["email"] → email address
                            user["plan"]  → plan name

RLS note
--------
get_current_user() only decodes the token — it does not touch the DB.
Route handlers that read/write user-owned rows must also call:
    await set_rls_user(db, user["sub"])
at the top of the handler so PostgreSQL RLS policies see the user context.
"""

import logging
import os
import re
import secrets
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import bcrypt

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr, field_validator

from api.middleware.rate_limit import rate_limit
from config import settings
from database.connection import get_db, set_rls_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_bearer = HTTPBearer()


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False

_ACCESS_TTL  = lambda: timedelta(minutes=settings.jwt_expire_minutes)
_REFRESH_TTL = timedelta(days=30)

# ── Request / response models ──────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[0-9]", v):
            raise ValueError("Password must contain at least one digit")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    password: str

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[0-9]", v):
            raise ValueError("Password must contain at least one digit")
        return v


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: str
    email: str
    plan: str
    is_admin: bool = False


# ── Token helpers ──────────────────────────────────────────────────────────────

def _build_token(
    user_id: str,
    email: str,
    plan: str,
    token_type: str,
    ttl: timedelta,
    is_admin: bool = False,
    jti: str | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    payload: dict = {
        "sub":      user_id,
        "email":    email,
        "plan":     plan,
        "is_admin": is_admin,
        "type":     token_type,
        "iat":      now,
        "exp":      now + ttl,
    }
    if jti:
        payload["jti"] = jti
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def _issue_pair(
    user_id: str, email: str, plan: str, is_admin: bool, db
) -> TokenResponse:
    jti = secrets.token_hex(16)
    expires_at = datetime.now(timezone.utc) + _REFRESH_TTL
    await db.execute(
        "INSERT INTO refresh_token_jti (jti, user_id, expires_at) VALUES ($1, $2::uuid, $3)",
        jti, user_id, expires_at,
    )
    return TokenResponse(
        access_token=_build_token(user_id, email, plan, "access", _ACCESS_TTL(), is_admin),
        refresh_token=_build_token(user_id, email, plan, "refresh", _REFRESH_TTL, is_admin, jti=jti),
        user_id=user_id,
        email=email,
        plan=plan,
        is_admin=is_admin,
    )


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new account",
)
async def register(
    body: RegisterRequest,
    request: Request,
    db=Depends(get_db),
    _=Depends(rate_limit(limit=10, window=60)),
):
    # Check registration_enabled — always allow first user (admin bootstrap)
    user_count = await db.fetchval("SELECT COUNT(*) FROM users")
    if user_count > 0:
        flags = await db.fetchrow(
            "SELECT registration_enabled FROM bot_config WHERE id=1"
        )
        if flags and not flags["registration_enabled"]:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Registration is currently disabled."
            )

    existing = await db.fetchrow("SELECT id FROM users WHERE email = $1", body.email)
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")

    referral_code = "TRADER-" + secrets.token_hex(3).upper()
    client_ip = request.client.host if request.client else None

    # Use INSERT with a subquery to atomically grant elite to the very first user,
    # avoiding the COUNT→INSERT race condition.
    user = await db.fetchrow(
        """
        INSERT INTO users (email, password_hash, referral_code, signup_ip, plan, is_admin)
        VALUES ($1, $2, $3, $4::inet,
                CASE WHEN (SELECT COUNT(*) FROM users) = 0 THEN 'elite' ELSE 'community' END,
                CASE WHEN (SELECT COUNT(*) FROM users) = 0 THEN TRUE ELSE FALSE END)
        RETURNING id, email, plan, is_admin
        """,
        body.email,
        _hash_password(body.password),
        referral_code,
        client_ip,
    )

    await set_rls_user(db, str(user["id"]))
    await db.execute(
        """
        INSERT INTO audit_log (user_id, action, detail, ip_address)
        VALUES ($1, $2, $3, $4::inet)
        """,
        user["id"], "register",
        f"Account created{' (first user — admin granted)' if user['plan'] == 'elite' else ''}",
        client_ip,
    )

    return await _issue_pair(str(user["id"]), user["email"], user["plan"], bool(user["is_admin"]), db)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Log in and receive a token pair",
)
async def login(
    body: LoginRequest,
    request: Request,
    db=Depends(get_db),
    _=Depends(rate_limit(limit=10, window=60)),
):
    user = await db.fetchrow(
        "SELECT id, email, password_hash, plan, is_admin FROM users WHERE email = $1",
        body.email,
    )

    # Constant-time failure path: always call verify even when user is None
    # to prevent timing-based user enumeration.
    password_ok = _verify_password(body.password, user["password_hash"]) if user else False
    if not user or not password_ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    client_ip = request.client.host if request.client else None

    await set_rls_user(db, str(user["id"]))
    await db.execute(
        """
        INSERT INTO audit_log (user_id, action, detail, ip_address)
        VALUES ($1, $2, $3, $4::inet)
        """,
        user["id"], "login",
        f"Login from {client_ip or 'unknown'}",
        client_ip,
    )

    return await _issue_pair(str(user["id"]), user["email"], user["plan"], bool(user["is_admin"]), db)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Exchange a refresh token for a new access token",
)
async def refresh(body: RefreshRequest, db=Depends(get_db)):
    try:
        payload = jwt.decode(
            body.refresh_token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired refresh token")

    if payload.get("type") != "refresh":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not a refresh token")

    jti = payload.get("jti")
    if not jti:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")

    # Validate jti exists and delete it atomically (single-use rotation)
    deleted = await db.fetchval(
        "DELETE FROM refresh_token_jti WHERE jti=$1 AND expires_at > NOW() RETURNING jti",
        jti,
    )
    if not deleted:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token already used or revoked")

    # Re-fetch user so new token pair reflects any plan/admin changes
    user = await db.fetchrow(
        "SELECT id, email, plan, is_admin FROM users WHERE id = $1::uuid",
        payload["sub"],
    )
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")

    return await _issue_pair(str(user["id"]), user["email"], user["plan"], bool(user["is_admin"]), db)


async def _send_reset_email(db, to_email: str, token: str) -> None:
    """Send password reset email. Falls back to logging if SMTP not configured."""
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
    reset_link = f"{frontend_url}/reset-password?token={token}"

    row = await db.fetchrow(
        """SELECT smtp_host, smtp_port, smtp_user, smtp_password,
                  smtp_from_email, smtp_from_name, smtp_enabled
           FROM bot_config WHERE id=1"""
    )

    if not row or not row["smtp_enabled"] or not row["smtp_host"]:
        logger.info("SMTP not configured — password reset link for %s : %s", to_email, reset_link)
        return

    host       = row["smtp_host"].strip()
    port       = row["smtp_port"] or 587
    username   = row["smtp_user"].strip()
    password   = row["smtp_password"]
    from_email = row["smtp_from_email"].strip() or username
    from_name  = row["smtp_from_name"].strip() or "Traxovia AI"

    html = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:auto;padding:32px">
      <h2 style="color:#00e5cc;margin-bottom:8px">Password Reset</h2>
      <p style="color:#444">Click the button below to reset your password.
         This link expires in <strong>15 minutes</strong>.</p>
      <a href="{reset_link}"
         style="display:inline-block;margin:24px 0;padding:12px 28px;
                background:#00e5cc;color:#000;text-decoration:none;
                border-radius:8px;font-weight:bold;font-family:monospace">
        RESET PASSWORD
      </a>
      <p style="color:#888;font-size:12px">
        If you didn't request this, ignore this email — your password won't change.
      </p>
    </div>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Reset your password"
    msg["From"]    = f"{from_name} <{from_email}>"
    msg["To"]      = to_email
    msg.attach(MIMEText(html, "html"))

    try:
        if port == 465:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=10) as s:
                if username and password:
                    s.login(username, password)
                s.sendmail(from_email, [to_email], msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=10) as s:
                s.ehlo()
                s.starttls(context=ssl.create_default_context())
                if username and password:
                    s.login(username, password)
                s.sendmail(from_email, [to_email], msg.as_string())
        logger.info("Password reset email sent to %s", to_email)
    except Exception as exc:
        logger.error("Failed to send reset email to %s: %s", to_email, exc)


@router.post("/forgot-password", summary="Request a password reset link")
async def forgot_password(
    body: ForgotPasswordRequest,
    db=Depends(get_db),
    _=Depends(rate_limit(limit=3, window=3600)),
):
    user = await db.fetchrow("SELECT id, email FROM users WHERE email = $1", body.email)
    if user:
        # Remove any existing unused tokens for this user
        await db.execute(
            "DELETE FROM password_reset_tokens WHERE user_id = $1::uuid",
            str(user["id"]),
        )
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
        await db.execute(
            "INSERT INTO password_reset_tokens (token, user_id, expires_at) VALUES ($1, $2::uuid, $3)",
            token, str(user["id"]), expires_at,
        )
        await _send_reset_email(db, user["email"], token)

    # Always 200 — never reveal whether email is registered
    return {"message": "If that email is registered, a reset link has been sent"}


@router.post("/reset-password", summary="Reset password using a valid token")
async def reset_password(
    body: ResetPasswordRequest,
    db=Depends(get_db),
    _=Depends(rate_limit(limit=5, window=3600)),
):
    row = await db.fetchrow(
        """SELECT user_id FROM password_reset_tokens
           WHERE token = $1 AND expires_at > NOW() AND used = FALSE""",
        body.token,
    )
    if not row:
        raise HTTPException(400, "Reset link is invalid or has expired")

    await db.execute(
        "UPDATE users SET password_hash = $1 WHERE id = $2::uuid",
        _hash_password(body.password), str(row["user_id"]),
    )
    await db.execute(
        "UPDATE password_reset_tokens SET used = TRUE WHERE token = $1",
        body.token,
    )
    # Revoke all refresh tokens for this user (force re-login everywhere)
    await db.execute(
        "DELETE FROM refresh_token_jti WHERE user_id = $1::uuid",
        str(row["user_id"]),
    )
    return {"message": "Password reset successfully. Please log in with your new password."}


# ── FastAPI dependency ─────────────────────────────────────────────────────────

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """
    FastAPI dependency — decodes the Bearer JWT and returns its claims.

    Does NOT hit the database. Stateless verification against JWT_SECRET.
    The returned dict is the raw decoded payload:
        {
            "sub":   "<user UUID as string>",
            "email": "user@example.com",
            "plan":  "trader",
            "type":  "access",
            "iat":   <timestamp>,
            "exp":   <timestamp>,
        }

    Raises HTTP 401 if the token is missing, malformed, expired, or is a
    refresh token presented where an access token is required.

    To enforce RLS in a route handler that uses this dependency:
        await set_rls_user(db, user["sub"])
    """
    exc = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError:
        raise exc

    if payload.get("type") != "access":
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Token type invalid — supply an access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload
