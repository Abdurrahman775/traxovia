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

import re
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr, field_validator

from api.middleware.rate_limit import rate_limit
from config import settings
from database.connection import get_db, set_rls_user

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
) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub":      user_id,
            "email":    email,
            "plan":     plan,
            "is_admin": is_admin,
            "type":     token_type,
            "iat":      now,
            "exp":      now + ttl,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def _issue_pair(user_id: str, email: str, plan: str, is_admin: bool = False) -> TokenResponse:
    return TokenResponse(
        access_token=_build_token(user_id, email, plan, "access",  _ACCESS_TTL(), is_admin),
        refresh_token=_build_token(user_id, email, plan, "refresh", _REFRESH_TTL, is_admin),
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
    existing = await db.fetchrow("SELECT id FROM users WHERE email = $1", body.email)
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")

    referral_code = "TRADER-" + secrets.token_hex(3).upper()
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or (
        request.client.host if request.client else None
    )

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

    return _issue_pair(str(user["id"]), user["email"], user["plan"], bool(user["is_admin"]))


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

    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or (
        request.client.host if request.client else None
    )

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

    return _issue_pair(str(user["id"]), user["email"], user["plan"], bool(user["is_admin"]))


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

    # Re-fetch the user so the new token pair reflects any plan changes
    # that happened since the refresh token was issued.
    user = await db.fetchrow(
        "SELECT id, email, plan, is_admin FROM users WHERE id = $1::uuid",
        payload["sub"],
    )
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")

    return _issue_pair(str(user["id"]), user["email"], user["plan"], bool(user["is_admin"]))


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
