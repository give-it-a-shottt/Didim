"""노트 목록 API 테스트 (F-004 — 기록 · 복습 홈 노트 목록, 사용자 확인 2026-11-11).

내 노트만(D-004), 최근 올린 것부터, 조각 수 · 문제 수, 원문은 넣지 않음, 상한을 넘으면 목록은 자르고 전체 수는 그대로.
"""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import SESSION_COOKIE_NAME, Settings
from app.db.models import Note, Quiz
from app.services.auth_service import GoogleProfile, create_session_token, get_or_create_google_user
from app.services.chunking import split_markdown
from app.services.note_service import create_note_for_user, list_note_summaries_for_user

BASE_TIME = datetime(2026, 11, 1, tzinfo=timezone.utc)


def _user(db: Session, sub: str) -> int:
    return get_or_create_google_user(db, GoogleProfile(sub=sub, email=f"{sub}@example.com", name=sub)).id


def _login(client: TestClient, db: Session, settings: Settings, sub: str) -> int:
    user_id = _user(db, sub)
    client.cookies.set(SESSION_COOKIE_NAME, create_session_token(user_id, settings.session_secret))
    return user_id


def _note(db: Session, user_id: int, title: str, sections: int = 2, minutes: int = 0) -> Note:
    content = f"# {title}\n" + "".join(f"\n## 구역 {n}\n{title} 내용 {n}\n" for n in range(sections))
    note = create_note_for_user(db, user_id=user_id, title=title, content=content, chunks=split_markdown(content))
    note.created_at = BASE_TIME + timedelta(minutes=minutes)  # 올린 순서를 정해 둔다
    db.commit()
    return note


def _quiz_on_first_chunk(db: Session, note: Note) -> None:
    chunk = note.chunks[0]
    quote = chunk.content.strip()
    start = chunk.start_offset + chunk.content.index(quote)
    db.add(
        Quiz(
            user_id=note.user_id,
            note_id=note.id,
            chunk_id=chunk.id,
            kind="ox",
            question="맞나요?",
            choices=["O", "X"],
            answer_index=0,
            explanation="원문에 있어요.",
            quote=quote,
            quote_start=start,
            quote_end=start + len(quote),
        )
    )
    db.commit()


def test_lists_only_my_notes_newest_first_with_counts(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    user_id = _login(client, db_session, test_settings, "list-me")
    older = _note(db_session, user_id, "먼저 올린 노트", sections=2, minutes=0)
    newer = _note(db_session, user_id, "나중 올린 노트", sections=3, minutes=5)
    _quiz_on_first_chunk(db_session, older)
    other = _note(db_session, _user(db_session, "list-other"), "남의 노트", minutes=10)
    _quiz_on_first_chunk(db_session, other)

    response = client.get("/api/notes")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [(n["id"], n["title"], n["chunk_count"], n["quiz_count"]) for n in body["notes"]] == [
        (newer.id, "나중 올린 노트", len(newer.chunks), 0),
        (older.id, "먼저 올린 노트", len(older.chunks), 1),
    ]
    assert not {"content", "chunks"} & body["notes"][0].keys()  # 목록에는 원문을 보내지 않는다


def test_empty_list_for_new_user(client: TestClient, db_session: Session, test_settings: Settings) -> None:
    _login(client, db_session, test_settings, "list-empty")

    assert client.get("/api/notes").json() == {"total": 0, "notes": []}


def test_list_requires_login(client: TestClient) -> None:
    assert client.get("/api/notes").status_code == 401


def test_list_is_capped_but_total_is_full(db_session: Session) -> None:
    user_id = _user(db_session, "list-cap")
    for minutes in range(3):
        _note(db_session, user_id, f"노트 {minutes}", minutes=minutes)

    page = list_note_summaries_for_user(db_session, user_id=user_id, limit=2)

    assert page.total == 3
    assert [note.title for note in page.notes] == ["노트 2", "노트 1"]
