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

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, field_validator

from config import settings
from database.connection import get_db, set_rls_user

router = APIRouter(prefix="/auth", tags=["auth"])

_bearer = HTTPBearer()
_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

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


# ── Token helpers ──────────────────────────────────────────────────────────────

def _build_token(
    user_id: str,
    email: str,
    plan: str,
    token_type: str,
    ttl: timedelta,
) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub":   user_id,
            "email": email,
            "plan":  plan,
            "type":  token_type,
            "iat":   now,
            "exp":   now + ttl,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def _issue_pair(user_id: str, email: str, plan: str) -> TokenResponse:
    return TokenResponse(
        access_token=_build_token(user_id, email, plan, "access",  _ACCESS_TTL()),
        refresh_token=_build_token(user_id, email, plan, "refresh", _REFRESH_TTL),
        user_id=user_id,
        email=email,
        plan=plan,
    )


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new account",
)
async def register(body: RegisterRequest, request: Request, db=Depends(get_db)):
    existing = await db.fetchrow("SELECT id FROM users WHERE email = $1", body.email)
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")

    referral_code = "TRADER-" + secrets.token_hex(3).upper()
    client_ip = request.client.host if request.client else None

    user = await db.fetchrow(
        """
        INSERT INTO users (email, password_hash, referral_code, signup_ip)
        VALUES ($1, $2, $3, $4::inet)
        RETURNING id, email, plan
        """,
        body.email,
        _pwd.hash(body.password),
        referral_code,
        client_ip,
    )

    # Set RLS context so the audit_log INSERT policy passes within this
    # transaction. We now know the user_id from the INSERT above.
    await set_rls_user(db, str(user["id"]))
    await db.execute(
        """
        INSERT INTO audit_log (user_id, action, detail, ip_address)
        VALUES ($1, $2, $3, $4::inet)
        """,
        user["id"], "register", "Account created", client_ip,
    )

    return _issue_pair(str(user["id"]), user["email"], user["plan"])


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Log in and receive a token pair",
)
async def login(body: LoginRequest, request: Request, db=Depends(get_db)):
    user = await db.fetchrow(
        "SELECT id, email, password_hash, plan FROM users WHERE email = $1",
        body.email,
    )

    # Constant-time failure path: always call verify even when user is None
    # to prevent timing-based user enumeration.
    password_ok = _pwd.verify(body.password, user["password_hash"]) if user else False
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

    return _issue_pair(str(user["id"]), user["email"], user["plan"])


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
        "SELECT id, email, plan FROM users WHERE id = $1::uuid",
        payload["sub"],
    )
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")

    return _issue_pair(str(user["id"]), user["email"], user["plan"])


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
