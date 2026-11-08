from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """서버가 살아 있는지만 확인한다. DB · 로그인과 관계없이 항상 응답한다."""
    return {"status": "ok"}
