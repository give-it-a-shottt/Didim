from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import auth, health, notes
from app.api.upload_limit import ImportUploadGuard
from app.db.session import dispose_engine, ensure_db_ready


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    ensure_db_ready()
    yield
    dispose_engine()


app = FastAPI(title="Didim API", lifespan=lifespan)

# 기록 가져오기는 본문을 다 받기 전에 로그인 쿠키 · 크기부터 본다(F-002). 라우터보다 먼저 돌아야 해서 미들웨어로 둔다.
app.add_middleware(ImportUploadGuard)

# 모든 경로를 /api 아래에 둔다. 브라우저는 Next.js의 /api/* 프록시를 거쳐 들어온다. (D-010, Q-012)
app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(notes.router, prefix="/api")
