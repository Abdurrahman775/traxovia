import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import settings
from database.connection import create_pool, close_pool
from database.migrate import run_migrations
from api.auth import router as auth_router
from api.billing import router as billing_router
from api.routes.signals import router as signals_router
from api.routes.analytics import router as analytics_router
from api.routes.trades import router as trades_router
from api.routes.regime import router as regime_router
from api.routes.settings import router as settings_router
from api.routes.auditlog import router as auditlog_router
from api.routes.model import router as model_router
from api.routes.community import router as community_router
from api.routes.referral import router as referral_router
from api.routes.admin import router as admin_router
from api.routes.prices import router as prices_router
from api.routes.profile import router as profile_router
from api.routes.data_management import router as data_mgmt_router
from api.routes.news import router as news_router


pathlib.Path("static/logos").mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_pool()
    await run_migrations()
    yield
    await close_pool()


app = FastAPI(title="Traxovia AI", version="3.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(auth_router)
app.include_router(billing_router)
app.include_router(signals_router)
app.include_router(analytics_router)
app.include_router(trades_router)
app.include_router(regime_router)
app.include_router(settings_router)
app.include_router(auditlog_router)
app.include_router(model_router)
app.include_router(community_router)
app.include_router(referral_router)
app.include_router(admin_router)
app.include_router(prices_router)
app.include_router(profile_router)
app.include_router(data_mgmt_router)
app.include_router(news_router)
