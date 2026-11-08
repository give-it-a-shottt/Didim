from fastapi import FastAPI

from app.api import health

app = FastAPI(title="Didim API")

# 모든 경로를 /api 아래에 둔다. 브라우저는 Next.js의 /api/* 프록시를 거쳐 들어온다. (D-010, Q-012)
app.include_router(health.router, prefix="/api")
