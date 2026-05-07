"""
Seed an admin user into the users table.
Inserts only if the email does not already exist.

Usage:
    cd /home/kira/trading-bot
    python scripts/seed_admin.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from passlib.context import CryptContext
from database.connection import get_db_direct

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

ADMIN_EMAIL = os.environ.get("SEED_ADMIN_EMAIL", "admin@tradingai.com")
ADMIN_PASSWORD = os.environ.get("SEED_ADMIN_PASSWORD")
ADMIN_PLAN = "elite"


async def seed():
    if not ADMIN_PASSWORD:
        print("ERROR: SEED_ADMIN_PASSWORD environment variable is required.")
        sys.exit(1)
    async with get_db_direct() as db:
        result = await db.fetchrow("SELECT id FROM users WHERE email = $1", ADMIN_EMAIL)
        if result:
            print(f"User {ADMIN_EMAIL} already exists — skipping.")
            return

        hashed = _pwd.hash(ADMIN_PASSWORD)
        await db.execute(
            "INSERT INTO users (email, password_hash, plan) VALUES ($1, $2, $3)",
            ADMIN_EMAIL, hashed, ADMIN_PLAN,
        )
        print(f"Admin user {ADMIN_EMAIL} created with plan '{ADMIN_PLAN}'.")


if __name__ == "__main__":
    asyncio.run(seed())
