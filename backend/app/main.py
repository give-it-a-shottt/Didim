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
from app.api.security_headers import SecurityHeaders
from app.api.upload_limit import ImportUploadGuard
from app.config import api_docs_urls, check_login_allowlist_from_env, load_settings
from app.db.session import dispose_engine, ensure_db_ready

# 운영에서 허용 목록을 빠뜨리면 앱을 불러오는 순간 멈춘다(F-015). 시작 처리(lifespan)가 아니라 여기서 — 배포 런타임이
# lifespan을 건너뛰거나 시작 오류를 삼켜도 열린 채로 뜨지 않게(D-032, F-016 1차 리뷰 R2).
check_login_allowlist_from_env()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    ensure_db_ready()
    yield
    dispose_engine()


# 문서 경로는 앱을 만들 때 정해져서, 시작할 때의 환경변수로 한 번 정한다(운영이면 끔 — D-032)
app = FastAPI(title="Didim API", lifespan=lifespan, **api_docs_urls(load_settings()))

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

# 가장 바깥(마지막에 더한 미들웨어가 먼저 돈다) — 가드의 403 · 413까지 모든 응답에 붙는다(D-032)
app.add_middleware(SecurityHeaders)
