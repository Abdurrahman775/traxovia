from contextlib import asynccontextmanager

from fastapi import FastAPI

from database.connection import create_pool, close_pool
from api.auth import router as auth_router
from api.billing import router as billing_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_pool()
    yield
    await close_pool()


app = FastAPI(title="Trading AI SaaS", version="3.0.0", lifespan=lifespan)

app.include_router(auth_router)
app.include_router(billing_router)
