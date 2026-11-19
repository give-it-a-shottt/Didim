"""Vercel 진입 파일(D-032) — Vercel의 FastAPI 지원은 index.py 같은 정해진 파일에서 `app`을 찾는다.

앱은 app/main.py에 있다. 로컬 실행은 그대로 `uvicorn app.main:app`.
"""

from app.main import app

__all__ = ["app"]
