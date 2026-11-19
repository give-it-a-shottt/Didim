from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import (
    applications,
    auth,
    cards,
    demo,
    drafts,
    health,
    home,
    interview,
    notes,
    notion,
    quizzes,
    report,
    search,
)
from app.api.sample_guard import SampleReadOnlyGuard
from app.api.upload_limit import ImportUploadGuard
from app.config import check_login_allowlist_at_startup
from app.db.session import dispose_engine, ensure_db_ready


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    check_login_allowlist_at_startup()  # 운영에서 허용 목록을 빠뜨리면 시작하지 않는다(F-015)
    ensure_db_ready()
    yield
    dispose_engine()


app = FastAPI(title="Didim API", lifespan=lifespan)

# 기록 가져오기는 본문을 다 받기 전에 로그인 쿠키 · 크기부터 본다(F-002). 라우터보다 먼저 돌아야 해서 미들웨어로 둔다.
app.add_middleware(ImportUploadGuard)
# 샘플 체험 세션은 읽기만 한다(F-010, D-029). 나중에 더한 미들웨어가 바깥에서 먼저 돌아서, 샘플의 가져오기도 403으로 끝난다.
app.add_middleware(SampleReadOnlyGuard)

# 모든 경로를 /api 아래에 둔다. 브라우저는 Next.js의 /api/* 프록시를 거쳐 들어온다. (D-010, Q-012)
app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(notes.router, prefix="/api")
app.include_router(search.router, prefix="/api")
app.include_router(quizzes.router, prefix="/api")
app.include_router(cards.router, prefix="/api")
app.include_router(notion.router, prefix="/api")
app.include_router(applications.router, prefix="/api")
app.include_router(drafts.router, prefix="/api")
app.include_router(interview.router, prefix="/api")
app.include_router(demo.router, prefix="/api")
app.include_router(report.router, prefix="/api")
app.include_router(home.router, prefix="/api")
