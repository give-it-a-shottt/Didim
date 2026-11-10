"""기록 가져오기 테스트 (F-002, 1주차: 읽기 · 나누기).

설계 의도의 완료 기준(feature.md)과 짝지어 확인한다.
1. 파일마다 노트 1개 + 조각 여러 개, 제목은 첫 # 제목 또는 파일 이름
2. 제목(# ~ ###) 기준으로 나누고, 기준 길이를 넘으면 문단 경계에서 다시 자름
3. 같은 내용은 '중복'으로 알리고 저장하지 않음
4. 일부가 실패해도 성공한 파일은 저장, 실패는 이유와 함께
5. 결과 요약(노트 · 조각 · 중복 · 실패)
6. 다른 사용자와 섞이지 않음(D-004)
그리고 조각 위치 규칙: 조각 내용 == 노트 원문[start_offset:end_offset].
"""

import asyncio
import logging
import re
import time
import tracemalloc
from collections.abc import Iterator
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from starlette.types import Message, Receive, Scope, Send

from app.api.deps import get_settings
from app.api.upload_limit import BAD_PATH_DETAIL, IMPORT_PATH, ImportUploadGuard
from app.config import (
    BYTES_PER_MB,
    HEADING_PATH_TEXT_MAX_CHARS,
    MAX_CHUNKS_PER_NOTE,
    MAX_IMPORT_FILE_BYTES,
    MAX_IMPORT_FILES,
    MAX_IMPORT_REQUEST_BYTES,
    SESSION_COOKIE_NAME,
    Settings,
)
from app.db.models import Chunk, Note
from app.importers.base import UnreadableFileError
from app.importers.markdown import UNNAMED_FILE, clean_filename, find_title, read_markdown_file
from app.main import app
from app.services import chunking, import_service
from app.services.auth_service import (
    GoogleProfile,
    create_session_token,
    get_or_create_google_user,
    verify_session_token,
)
from app.services.chunking import ChunkDraft, TooManyChunksError, split_markdown
from app.services.note_service import ChunkLocationError, create_note_for_user, list_notes_for_user

# --- 읽기(어댑터) ------------------------------------------------------------


def test_title_is_first_level1_heading_outside_code() -> None:
    content = "```bash\n# 설치 명령\n```\n\n## 소제목\n\n# React 정리\n본문"
    document = read_markdown_file("note.md", content.encode())
    assert document.title == "React 정리"
    assert document.source == "markdown"


def test_title_falls_back_to_file_name_and_keeps_sharp_in_text() -> None:
    assert read_markdown_file("운영체제.md", "본문만 있어요".encode()).title == "운영체제"
    assert read_markdown_file("c.md", "# C# 기초 #\n본문".encode()).title == "C# 기초"


def test_reading_strips_bom_and_normalizes_newlines() -> None:
    document = read_markdown_file("a.markdown", "\ufeff# 제목\r\n본문\r줄".encode())
    assert document.content == "# 제목\n본문\n줄"


@pytest.mark.parametrize(
    ("filename", "data", "reason"),
    [
        ("memo.txt", b"hello", "마크다운(.md) 파일만"),
        ("big.md", b"a" * (MAX_IMPORT_FILE_BYTES + 1), "1MB를 넘어요"),
        ("cp949.md", "한글".encode("cp949"), "UTF-8로 저장된 파일만"),
        ("binary.md", b"abc\x00def", "텍스트 파일이 아닌 것 같아요"),
        ("empty.md", b"  \n\t\n", "내용이 비어 있어요"),
    ],
)
def test_unreadable_files_get_a_reason(filename: str, data: bytes, reason: str) -> None:
    with pytest.raises(UnreadableFileError, match=re.escape(reason)):
        read_markdown_file(filename, data)


def test_clean_filename_drops_folders() -> None:
    assert clean_filename("../../etc/passwd.md") == "passwd.md"
    assert clean_filename("C:\\Users\\me\\노트.md") == "노트.md"
    assert clean_filename("") == UNNAMED_FILE
    assert clean_filename(None) == UNNAMED_FILE


# --- 나누기 ------------------------------------------------------------------


def _assert_chunks_are_slices(content: str, chunks: list[ChunkDraft]) -> None:
    """모든 조각이 원문의 구간이고, 원문 순서대로 겹치지 않는다."""
    previous_end = 0
    for chunk in chunks:
        assert content[chunk.start_offset : chunk.end_offset] == chunk.content
        assert chunk.content == chunk.content.strip()
        assert chunk.start_offset >= previous_end
        previous_end = chunk.end_offset


def test_split_by_headings_with_paths() -> None:
    content = (
        "들어가는 말\n\n"
        "# React\n\n"  # 제목만 있는 구역 → 조각 없음
        "## useEffect\n의존성 배열\n\n"
        "#### 세부 메모\n4단계 제목은 나누지 않는다\n\n"
        "### 정리\n요약\n\n"
        "# 운영체제\n"
        "### 스케줄링\n라운드 로빈"
    )
    chunks = split_markdown(content)

    assert [chunk.heading_path for chunk in chunks] == [
        "",
        "# React > ## useEffect",
        "# React > ## useEffect > ### 정리",
        "# 운영체제 > ### 스케줄링",
    ]
    assert "#### 세부 메모" in chunks[1].content
    assert chunks[1].content.startswith("## useEffect")
    _assert_chunks_are_slices(content, chunks)


def test_hash_lines_inside_code_blocks_are_not_headings() -> None:
    content = "## 설치\n```bash\n# 패키지 설치\npip install x\n```\n\n~~~\n# 또 다른 주석\n~~~"
    chunks = split_markdown(content)
    assert len(chunks) == 1
    assert chunks[0].heading_path == "## 설치"
    _assert_chunks_are_slices(content, chunks)


def test_long_section_is_split_at_paragraph_boundaries() -> None:
    paragraphs = [f"문단{index} " + "가" * 30 for index in range(10)]  # 문단마다 약 35자
    content = "## 긴 구역\n" + "\n\n".join(paragraphs)
    chunks = split_markdown(content, max_chars=100)

    assert len(chunks) > 1
    assert all(len(chunk.content) <= 100 for chunk in chunks)
    assert all(chunk.heading_path == "## 긴 구역" for chunk in chunks)
    # 문단 중간에서 자르지 않는다: 모든 조각은 문단 끝("가")으로 끝난다
    assert all(chunk.content.endswith("가") for chunk in chunks)
    _assert_chunks_are_slices(content, chunks)


def test_too_long_paragraph_and_line_are_still_cut_without_losing_text() -> None:
    long_line = "나" * 250
    content = "# 제목\n" + "짧은 줄\n" * 5 + long_line
    chunks = split_markdown(content, max_chars=100)

    assert all(len(chunk.content) <= 100 for chunk in chunks)
    _assert_chunks_are_slices(content, chunks)
    joined = "".join(chunk.content for chunk in chunks)
    assert re.sub(r"\s", "", joined) == re.sub(r"\s", "", content)  # 잃어버린 글자가 없다


def test_boundary_cases_of_headings_and_code_blocks() -> None:
    # 닫히지 않은 코드 블록: 끝까지 코드로 본다(안의 #은 제목 아님)
    unclosed = "## 설치\n```\n# 주석\n## 이것도 주석"
    assert [chunk.heading_path for chunk in split_markdown(unclosed)] == ["## 설치"]

    # ```js 같은 줄은 블록을 닫지 않는다(CommonMark) → 그 뒤의 #도 아직 코드
    info_line = "## 예시\n````markdown\n```js\n# 코드 안\n```\n````\n## 다음\n본문"
    assert [chunk.heading_path for chunk in split_markdown(info_line)] == ["## 예시", "## 다음"]

    # 4칸 들여쓴 줄은 제목이 아니다(들여쓴 코드)
    indented = "## 구역\n본문\n\n    # 들여쓴 코드\n"
    assert [chunk.heading_path for chunk in split_markdown(indented)] == ["## 구역"]

    # 제목 단계를 건너뛰어도(# → ###) 경로가 이어진다
    skipped = "# 큰 제목\n### 작은 제목\n본문"
    assert [chunk.heading_path for chunk in split_markdown(skipped)] == ["# 큰 제목 > ### 작은 제목"]

    # 글이 없는 제목("# ", "## ##")은 제목으로 보지 않는다
    assert find_title("# \n## ##\n# 진짜 제목") == "진짜 제목"


def test_chunk_length_boundary_is_inclusive() -> None:
    exactly = "가" * 100
    assert len(split_markdown(exactly, max_chars=100)) == 1
    over = "가" * 50 + "\n\n" + "나" * 50  # 102자 → 문단 경계에서 둘로
    assert [chunk.content for chunk in split_markdown(over, max_chars=100)] == ["가" * 50, "나" * 50]


def test_heading_regex_is_fast_on_long_whitespace_lines() -> None:
    """R2 지적(ReDoS): 공백이 아주 긴 제목 줄도 바로 끝나야 한다(예전 정규식은 공백 1만6천 개에 1.5초)."""
    line = "# a" + " " * 200_000 + "b"
    started = time.perf_counter()
    assert find_title(line) is not None
    split_markdown(line + "\n본문")
    assert time.perf_counter() - started < 1.0


def test_heading_path_is_capped_even_with_huge_titles() -> None:
    """R2 지적: 아주 긴 제목이 조각마다 복사돼 커지지 않는다. 한 단계는 상한에서 자르고 '…'을 붙인다."""
    content = "# " + "x" * 20_000 + "\n" + "### a\nb\n" * 50
    chunks = split_markdown(content)
    assert len(chunks) == 50
    first_label = chunks[0].heading_path.split(" > ")[0]
    assert first_label == "# " + "x" * HEADING_PATH_TEXT_MAX_CHARS + "…"
    assert all(len(chunk.heading_path) < 3 * (HEADING_PATH_TEXT_MAX_CHARS + 10) for chunk in chunks)
    _assert_chunks_are_slices(content, chunks)


def test_note_service_refuses_chunks_that_do_not_match_the_original(db_session: Session) -> None:
    user = get_or_create_google_user(db_session, GoogleProfile(sub="s-loc", email="l@example.com", name="L"))
    wrong = ChunkDraft(heading_path="", start_offset=0, end_offset=3, content="다른 글")
    with pytest.raises(ChunkLocationError):
        create_note_for_user(db_session, user_id=user.id, title="t", content="원문 내용", chunks=[wrong])
    assert list_notes_for_user(db_session, user_id=user.id) == []


# --- API ---------------------------------------------------------------------


def _sign_in(client: TestClient, db_session: Session, settings: Settings, sub: str) -> int:
    user = get_or_create_google_user(db_session, GoogleProfile(sub=sub, email=f"{sub}@example.com", name=sub))
    client.cookies.set(SESSION_COOKIE_NAME, create_session_token(user.id, settings.session_secret))
    return user.id


def _md(name: str, text: str) -> tuple[str, tuple[str, bytes, str]]:
    return ("files", (name, text.encode("utf-8"), "text/markdown"))


def test_import_requires_login(client: TestClient) -> None:
    response = client.post("/api/notes/import", files=[_md("a.md", "# A\n본문")])
    assert response.status_code == 401


def test_import_saves_notes_and_chunks_for_the_signed_in_user(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    user_id = _sign_in(client, db_session, test_settings, "importer")
    react = "# React 정리\n\n## useState\n상태\n\n## useEffect\n부수 효과"
    response = client.post(
        "/api/notes/import",
        files=[_md("react.md", react), _md("os.md", "프로세스와 스레드")],
        data={"kind": "project"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == {"notes": 2, "chunks": 3, "duplicates": 0, "failed": 0}
    assert [item["title"] for item in body["imported"]] == ["React 정리", "os"]

    notes = db_session.execute(select(Note).where(Note.user_id == user_id).order_by(Note.id)).scalars().all()
    assert [note.kind for note in notes] == ["project", "project"]
    chunks = db_session.execute(select(Chunk).where(Chunk.note_id == notes[0].id).order_by(Chunk.position)).scalars()
    for chunk in chunks:
        assert chunk.user_id == user_id
        assert notes[0].content[chunk.start_offset : chunk.end_offset] == chunk.content


def test_same_content_is_reported_as_duplicate(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    _sign_in(client, db_session, test_settings, "dup")
    text = "# 같은 노트\n본문\n"
    first = client.post(
        "/api/notes/import",
        files=[_md("a.md", text), _md("b.md", text.replace("\n", "\r\n"))],  # 같은 요청 안 · 줄바꿈만 다름
    ).json()
    assert first["summary"]["notes"] == 1
    assert first["duplicates"] == [
        {"filename": "b.md", "existing_note_id": first["imported"][0]["note_id"], "existing_title": "같은 노트"}
    ]

    again = client.post("/api/notes/import", files=[_md("c.md", text)]).json()
    assert again["summary"] == {"notes": 0, "chunks": 0, "duplicates": 1, "failed": 0}


def test_other_users_note_is_not_a_duplicate_and_not_revealed(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    """D-004: 중복 확인도 내 노트 안에서만 한다. B가 A와 같은 글을 올려도 A의 노트를 알려 주지 않는다."""
    text = "# 공통 정리\n같은 강의를 들었다"
    _sign_in(client, db_session, test_settings, "user-a")
    client.post("/api/notes/import", files=[_md("a.md", text)])

    user_b = _sign_in(client, db_session, test_settings, "user-b")
    body = client.post("/api/notes/import", files=[_md("b.md", text)]).json()

    assert body["summary"]["notes"] == 1
    assert body["duplicates"] == []
    assert [note.title for note in list_notes_for_user(db_session, user_id=user_b)] == ["공통 정리"]


def test_partial_failure_keeps_successful_files(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    _sign_in(client, db_session, test_settings, "partial")
    response = client.post(
        "/api/notes/import",
        files=[
            _md("ok.md", "# 성공\n본문"),
            ("files", ("memo.txt", b"text", "text/plain")),
            ("files", ("big.md", b"a" * (MAX_IMPORT_FILE_BYTES + 10), "text/markdown")),
            ("files", ("../secret/dir/broken.md", "한글".encode("cp949"), "text/markdown")),
        ],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == {"notes": 1, "chunks": 1, "duplicates": 0, "failed": 3}
    reasons = {item["filename"]: item["reason"] for item in body["failed"]}
    assert set(reasons) == {"memo.txt", "big.md", "broken.md"}  # 폴더 경로는 떼어 낸다
    assert "1MB" in reasons["big.md"]


def test_import_rejects_no_files_too_many_files_and_bad_kind(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    _sign_in(client, db_session, test_settings, "limits")

    no_files = client.post("/api/notes/import", data={"kind": "study"})
    assert no_files.status_code == 400
    assert no_files.json() == {"detail": "올릴 파일을 골라 주세요."}

    too_many = client.post(
        "/api/notes/import",
        files=[_md(f"{index}.md", f"노트 {index}") for index in range(MAX_IMPORT_FILES + 1)],
    )
    assert too_many.status_code == 400
    assert f"{MAX_IMPORT_FILES}개까지" in too_many.json()["detail"]

    bad_kind = client.post("/api/notes/import", files=[_md("a.md", "본문")], data={"kind": "auto"})
    assert bad_kind.status_code == 422


def test_total_size_over_limit_is_413_even_when_header_check_passes(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    """요청 전체는 머리말 상한(21MB) 아래지만 파일 합계가 20MB를 넘으면, 엔드포인트가 받은 뒤 413으로 막는다."""
    _sign_in(client, db_session, test_settings, "total")
    half = b"a" * (10 * 1024 * 1024 + 300 * 1024)  # 약 10.3MB × 2 = 20.6MB
    response = client.post(
        "/api/notes/import",
        files=[("files", ("a.md", half, "text/markdown")), ("files", ("b.md", half, "text/markdown"))],
    )
    assert response.status_code == 413
    assert list_notes_for_user(db_session, user_id=_sign_in(client, db_session, test_settings, "total")) == []


def test_title_only_file_fails_and_too_many_chunks_fails(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    """사용자 확인(F-002 1차 리뷰): 조각 0개(제목만) · 조각 상한 초과는 그 파일만 실패, 나머지는 저장."""
    user_id = _sign_in(client, db_session, test_settings, "chunk-rules")
    many = "### a\nb\n" * (MAX_CHUNKS_PER_NOTE + 1)
    body = client.post(
        "/api/notes/import",
        files=[_md("title-only.md", "# React\n## Hooks\n"), _md("many.md", many), _md("ok.md", "# 정상\n본문")],
    ).json()

    assert body["summary"] == {"notes": 1, "chunks": 1, "duplicates": 0, "failed": 2}
    reasons = {item["filename"]: item["reason"] for item in body["failed"]}
    assert "나눌 본문이 없어요" in reasons["title-only.md"]
    assert f"{MAX_CHUNKS_PER_NOTE:,}개 초과" in reasons["many.md"]
    assert [note.title for note in list_notes_for_user(db_session, user_id=user_id)] == ["정상"]


def test_save_failure_fails_only_that_file_and_logs_no_content(
    client: TestClient,
    db_session: Session,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """완료 기준 4: 두 번째 파일 저장이 DB 오류로 실패해도 첫 · 세 번째 파일은 저장되고, 로그에 원문이 없다."""
    user_id = _sign_in(client, db_session, test_settings, "save-fail")
    real_create = import_service.create_note_for_user

    def flaky_create(db: Session, **kwargs: object) -> Note:
        if kwargs["title"] == "실패할 노트":
            raise OperationalError("INSERT ...", {"content": "비밀 원문"}, Exception("db down"))
        return real_create(db, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(import_service, "create_note_for_user", flaky_create)
    with caplog.at_level(logging.ERROR, logger=import_service.__name__):
        body = client.post(
            "/api/notes/import",
            files=[_md("1.md", "# 첫 노트\n본문"), _md("2.md", "# 실패할 노트\n비밀 원문"), _md("3.md", "# 셋째\n본문")],
        ).json()

    assert body["summary"] == {"notes": 2, "chunks": 2, "duplicates": 0, "failed": 1}
    assert body["failed"] == [{"filename": "2.md", "reason": import_service.SAVE_FAILED_REASON}]
    assert sorted(note.title for note in list_notes_for_user(db_session, user_id=user_id)) == ["셋째", "첫 노트"]
    assert "OperationalError" in caplog.text
    assert "비밀 원문" not in caplog.text


def test_chunk_location_bug_fails_only_that_file(
    client: TestClient, db_session: Session, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3-1: 나누기가 원문과 다른 조각을 내도(버그) 500이 아니라 그 파일만 실패하고 앞 파일 결과는 돌아온다."""
    real_split = import_service.split_markdown

    def buggy_split(content: str, **kwargs: int) -> list[ChunkDraft]:
        if "버그" in content:
            return [ChunkDraft(heading_path="", start_offset=0, end_offset=2, content="다름")]
        return real_split(content, **kwargs)

    monkeypatch.setattr(import_service, "split_markdown", buggy_split)
    user_id = _sign_in(client, db_session, test_settings, "location-bug")
    response = client.post("/api/notes/import", files=[_md("ok.md", "# 정상\n본문"), _md("bug.md", "버그 노트")])

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == {"notes": 1, "chunks": 1, "duplicates": 0, "failed": 1}
    assert body["failed"] == [{"filename": "bug.md", "reason": import_service.SAVE_FAILED_REASON}]
    assert [note.title for note in list_notes_for_user(db_session, user_id=user_id)] == ["정상"]  # 버그 노트는 저장 안 됨


def test_duplicate_race_is_reported_as_duplicate(
    client: TestClient, db_session: Session, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """먼저 확인할 때는 없었는데 저장하려니 같은 원문이 있는 경우(동시에 두 번 올림) → 중복으로 알린다."""
    user_id = _sign_in(client, db_session, test_settings, "race")
    text = "# 경쟁\n같은 글"
    existing = create_note_for_user(db_session, user_id=user_id, title="경쟁", content=text, chunks=split_markdown(text))

    real_find = import_service.find_note_by_content_hash_for_user
    calls = {"count": 0}

    def find_misses_first_time(db: Session, **kwargs: object) -> Note | None:
        calls["count"] += 1
        return None if calls["count"] == 1 else real_find(db, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(import_service, "find_note_by_content_hash_for_user", find_misses_first_time)
    body = client.post("/api/notes/import", files=[_md("again.md", text)]).json()

    assert body["duplicates"] == [{"filename": "again.md", "existing_note_id": existing.id, "existing_title": "경쟁"}]
    assert body["summary"]["failed"] == 0


def test_duplicate_race_without_existing_note_fails_that_file(
    client: TestClient, db_session: Session, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """저장 때 중복 오류가 났는데 다시 찾아도 그 노트가 안 보이면(지워졌거나 다른 이유) 중복이 아니라 실패로 알린다."""
    user_id = _sign_in(client, db_session, test_settings, "race-missing")
    text = "# 사라진 노트\n본문"
    create_note_for_user(db_session, user_id=user_id, title="사라진 노트", content=text, chunks=split_markdown(text))
    monkeypatch.setattr(import_service, "find_note_by_content_hash_for_user", lambda db, **kwargs: None)

    body = client.post("/api/notes/import", files=[_md("again.md", text)]).json()

    assert body["failed"] == [{"filename": "again.md", "reason": import_service.SAVE_FAILED_REASON}]
    assert body["duplicates"] == []


def test_too_many_chunks_stops_splitting_early(monkeypatch: pytest.MonkeyPatch) -> None:
    """2차 R2: 상한을 훨씬 넘는 파일(1MB, 조각 13만 개 분량)도 상한 + 1개째에서 멈춘다 — 끝까지 나누지 않는다.

    시간 대신 '읽은 줄 수'로 확인한다(3차 R3 — 시간 비교는 느린 환경에서 흔들림). 줄마다 제목인지 한 번 보므로
    parse_heading 호출 수 = 읽은 줄 수다.
    """
    content = "### a\nb\n" * 131_000  # 26만 2천 줄
    calls = {"count": 0}
    real_parse_heading = chunking.parse_heading

    def counting_parse_heading(line: object) -> object:
        calls["count"] += 1
        return real_parse_heading(line)  # type: ignore[arg-type]

    monkeypatch.setattr(chunking, "parse_heading", counting_parse_heading)
    with pytest.raises(TooManyChunksError):
        split_markdown(content, max_chunks=MAX_CHUNKS_PER_NOTE)
    assert calls["count"] < 2 * (MAX_CHUNKS_PER_NOTE + 2) + 10  # 상한 근처까지만 읽음(전체는 262,000줄)
    assert len(split_markdown("### a\nb\n" * MAX_CHUNKS_PER_NOTE, max_chunks=MAX_CHUNKS_PER_NOTE)) == MAX_CHUNKS_PER_NOTE


def test_splitting_many_lines_keeps_memory_small() -> None:
    """3차 R2: 한 구역 · 한 문단에 줄이 아주 많아도 메모리는 줄 수가 아니라 조각 수에 비례한다.

    예전 구현은 줄마다 객체를 모아 두어 줄 100만 개짜리 1MB 파일이 약 180MB를 썼다. 20만 줄로 재서 10MB 아래인지 본다.
    """
    content = "## 큰 구역\n" + "가\n" * 200_000
    tracemalloc.start()
    try:
        chunks = split_markdown(content)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 10 * BYTES_PER_MB
    _assert_chunks_are_slices(content, chunks)
    assert all(len(chunk.content) <= 1500 for chunk in chunks)


def test_import_route_path_matches_the_upload_guard() -> None:
    """미들웨어가 지키는 경로(IMPORT_PATH)와 실제 라우터 경로가 같아야 한다. 라우터 경로를 바꾸면 여기서 실패한다."""
    assert "post" in app.openapi()["paths"].get(IMPORT_PATH, {})


class _AppWithSettings:
    """미들웨어가 설정을 찾는 곳(scope["app"].dependency_overrides)만 흉내 낸다."""

    def __init__(self, settings: Settings) -> None:
        self.dependency_overrides = {get_settings: lambda: settings}


def _call_guard(
    settings: Settings,
    headers: dict[str, str],
    body_chunks: list[bytes],
    path: str = IMPORT_PATH,
    root_path: str = "",
) -> tuple[int, int]:
    """미들웨어만 따로 돌린다. (응답 코드, 안쪽 앱이 실제로 받은 바이트 수)를 돌려준다."""
    received_by_app = 0

    async def inner_app(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal received_by_app
        while True:
            message = await receive()
            received_by_app += len(message.get("body", b""))
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    pending = [
        {"type": "http.request", "body": chunk, "more_body": index < len(body_chunks) - 1}
        for index, chunk in enumerate(body_chunks)
    ]

    async def receive() -> Message:
        return pending.pop(0) if pending else {"type": "http.disconnect"}

    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": root_path + path,
        "root_path": root_path,
        "headers": [(key.encode(), value.encode()) for key, value in headers.items()],
        "query_string": b"",
        "app": _AppWithSettings(settings),
    }
    try:
        asyncio.run(ImportUploadGuard(inner_app)(scope, receive, send))
    except Exception as exc:  # 받는 중 상한을 넘으면 HTTPException(413)이 안쪽 앱(FastAPI)으로 올라간다
        status = getattr(exc, "status_code", 500)
        return status, received_by_app
    return sent[0]["status"], received_by_app


def _signed_cookie(settings: Settings, user_id: int = 1) -> dict[str, str]:
    return {"cookie": f"{SESSION_COOKIE_NAME}={create_session_token(user_id, settings.session_secret)}"}


def test_upload_guard_checks_cookie_and_size_before_reading_the_body(test_settings: Settings) -> None:
    cookie = _signed_cookie(test_settings)
    small = [b"a" * 10]

    assert _call_guard(test_settings, {}, small) == (401, 0)  # 쿠키 없음 → 본문을 읽지 않고 401
    forged = {"cookie": f"{SESSION_COOKIE_NAME}=x"}
    assert _call_guard(test_settings, forged, small) == (401, 0)  # 이름만 맞는 가짜 쿠키도 본문 전에 401(2차 R2)
    too_large = {**cookie, "content-length": str(MAX_IMPORT_REQUEST_BYTES + 1)}
    assert _call_guard(test_settings, too_large, small) == (413, 0)
    assert _call_guard(test_settings, {**cookie, "content-length": "10"}, small) == (200, 10)
    assert _call_guard(test_settings, {}, small, path="/api/auth/me") == (200, 10)  # 다른 경로는 건드리지 않음


def test_upload_guard_returns_500_without_reading_body_when_auth_is_misconfigured(test_settings: Settings) -> None:
    """3차 R3: 서버 비밀키 설정이 틀렸으면(빈 SESSION_SECRET) 가드도 deps와 같이 500 — 본문은 읽지 않는다."""
    broken = replace(test_settings, session_secret="")
    assert _call_guard(broken, _signed_cookie(test_settings), [b"a" * 10]) == (500, 0)


def test_non_ascii_session_cookie_is_401_not_500(test_settings: Settings) -> None:
    """3차 R2: 쿠키에 ASCII가 아닌 글자가 있으면 예외(500)가 아니라 위조로 보고 401."""
    assert verify_session_token("é.x", test_settings.session_secret) is None
    assert _call_guard(test_settings, {"cookie": f"{SESSION_COOKIE_NAME}=é.x"}, [b"a" * 10]) == (401, 0)


def test_upload_guard_cannot_be_bypassed_by_path_tricks(test_settings: Settings) -> None:
    """2차 R2(위험): 끝 줄바꿈(%0A) 같은 제어 문자로 가드를 비켜 가지 못하고, root_path가 붙어도 가드가 걸린다."""
    small = [b"a" * 10]
    assert _call_guard(test_settings, {}, small, path=IMPORT_PATH + "\n") == (400, 0)
    assert _call_guard(test_settings, {}, small, path="/api/health\x00") == (400, 0)  # 어느 경로든
    assert _call_guard(test_settings, {}, small, root_path="/didim") == (401, 0)


def test_upload_guard_stops_body_without_content_length_once_over_limit(test_settings: Settings) -> None:
    """R2-1: 머리말이 없는(조각 전송) 요청도 실제로 받은 바이트가 상한을 넘는 순간 끊는다."""
    one_mb = b"a" * BYTES_PER_MB
    status, received = _call_guard(
        test_settings, _signed_cookie(test_settings), [one_mb] * (MAX_IMPORT_REQUEST_BYTES // BYTES_PER_MB + 5)
    )
    assert status == 413
    assert received <= MAX_IMPORT_REQUEST_BYTES


def test_newline_path_is_rejected_by_the_real_app(client: TestClient) -> None:
    """실제 앱에서도 줄바꿈이 붙은 가져오기 주소는 본문을 읽지 않고 400으로 끝난다."""
    response = client.post("/api/notes/import%0A", files=[_md("a.md", "# A\n본문")])
    assert response.status_code == 400
    assert response.json() == {"detail": BAD_PATH_DETAIL}  # 가드가 막음(라우터 · 폼 파싱까지 가지 않음)


def test_forged_cookie_gets_401_on_import(client: TestClient) -> None:
    """서명이 틀린 쿠키로 가져오기를 부르면 401(만료 · 위조 문구)."""
    client.cookies.set(SESSION_COOKIE_NAME, "forged-token")
    response = client.post("/api/notes/import", files=[_md("a.md", "# A\n본문")])
    assert response.status_code == 401
    assert response.json() == {"detail": "로그인이 만료되었어요. 다시 로그인해 주세요."}


def _chunked_multipart(total_bytes: int) -> Iterator[bytes]:
    boundary = "didimtestboundary"
    yield (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"big.md\"\r\n"
        "Content-Type: text/markdown\r\n\r\n"
    ).encode()
    sent = 0
    while sent < total_bytes:
        yield b"a" * BYTES_PER_MB
        sent += BYTES_PER_MB
    yield f"\r\n--{boundary}--\r\n".encode()


def test_chunked_upload_over_limit_gets_413_through_the_real_app(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    """머리말 없이 22MB를 흘려보내면 FastAPI가 본문을 읽다가 413을 돌려주고, 아무것도 저장하지 않는다."""
    user_id = _sign_in(client, db_session, test_settings, "chunked")
    response = client.post(
        "/api/notes/import",
        content=_chunked_multipart(22 * BYTES_PER_MB),
        headers={"content-type": "multipart/form-data; boundary=didimtestboundary"},
    )
    assert response.status_code == 413
    assert list_notes_for_user(db_session, user_id=user_id) == []
