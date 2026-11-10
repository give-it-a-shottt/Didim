from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import auth, health
from app.db.session import ensure_db_ready


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    ensure_db_ready()
    yield


app = FastAPI(title="Didim API", lifespan=lifespan)

# 모든 경로를 /api 아래에 둔다. 브라우저는 Next.js의 /api/* 프록시를 거쳐 들어온다. (D-010, Q-012)
app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
