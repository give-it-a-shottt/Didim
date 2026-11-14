"""지원(공고) 만들기 · 목록 · 상세 · 상태 바꾸기 · 삭제 (F-007 완료 기준 1 · 2 · 3 · 5).

- 공고는 사용자가 붙여 넣은 본문으로만 만든다. URL은 링크로 저장만 하고 서버가 읽지 않는다(D-002).
- 본문은 만든 뒤 고칠 수 없다 — 요구 역량의 공고 인용 위치가 본문 기준이라서. 바꿀 수 있는 것은 상태 · 마감일뿐.
- 목록은 D-day 순: 마감이 남은 것(가까운 순) → 마감이 지난 것(최근 지난 순) → 마감일 없음(최근 만든 순).
- 모든 조회에 user_id 조건을 건다(D-004). 남의 공고는 '없음'과 똑같이 답한다.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from urllib.parse import urlsplit

from sqlalchemy import and_, case, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.config import (
    APPLICATION_COMPANY_MAX_CHARS,
    APPLICATION_MAX_QUESTIONS,
    APPLICATION_QUESTION_CHAR_LIMIT_MAX,
    APPLICATION_QUESTION_MAX_CHARS,
    APPLICATION_ROLE_MAX_CHARS,
    APPLICATION_STATUS_DEFAULT,
    APPLICATION_STATUSES,
    APPLICATION_URL_MAX_CHARS,
    MAX_APPLICATION_LIST,
    POSTING_TEXT_MAX_CHARS,
)
from app.db.models import (
    Application,
    ApplicationQuestion,
    Card,
    PostingRequirement,
    RequirementMatch,
)
from app.korea_time import korea_today, now_utc
from app.services.text_clean import has_forbidden_control

CONTROL_CHAR_MESSAGE = "쓸 수 없는 글자(제어 문자)가 들어 있어요."
BAD_URL_MESSAGE = "공고 링크 형식이 틀렸어요."


class ApplicationNotFound(Exception):
    """내 공고가 아니거나 없는 공고."""


class QuestionsConflict(Exception):
    """화면이 본 문항 목록이 지금과 다르다(다른 탭이 먼저 넣거나 지움) — 저장하지 않는다(F-008 2차 리뷰 R2 · R3)."""


class InvalidApplicationInput(Exception):
    """입력이 비었거나 너무 김 · 형식이 틀림. 화면에 그대로 보여 줄 문구를 담는다."""


# --- 입력 정리 ---


def _one_line(value: str, *, label: str, max_chars: int) -> str:
    cleaned = " ".join(value.split())
    if has_forbidden_control(cleaned):
        raise InvalidApplicationInput(CONTROL_CHAR_MESSAGE)
    if not cleaned:
        raise InvalidApplicationInput(f"{label}을(를) 적어 주세요.")
    if len(cleaned) > max_chars:
        raise InvalidApplicationInput(f"{label}은(는) {max_chars}자까지 쓸 수 있어요.")
    return cleaned


def _clean_url(value: str | None) -> str | None:
    """링크로만 저장한다. http · https만 받는다 — 화면이 이 주소를 링크로 걸기 때문에(javascript: 같은 주소를 막음)."""
    if value is None or not value.strip():
        return None
    url = value.strip()
    if has_forbidden_control(url) or any(char.isspace() for char in url):
        raise InvalidApplicationInput(BAD_URL_MESSAGE)
    if len(url) > APPLICATION_URL_MAX_CHARS:
        raise InvalidApplicationInput(f"공고 링크는 {APPLICATION_URL_MAX_CHARS}자까지 쓸 수 있어요.")
    try:
        parts = urlsplit(url)
    except ValueError as exc:  # 'http://[abc'(괄호가 안 닫힌 IPv6) · 전각 문자가 섞인 주소 등
        raise InvalidApplicationInput(BAD_URL_MESSAGE) from exc
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        raise InvalidApplicationInput("공고 링크는 http:// 또는 https://로 시작해야 해요.")
    return url


def _clean_posting(value: str) -> str:
    """앞뒤 공백만 걷는다. 안쪽은 그대로 둔다 — 요구 역량의 공고 인용이 본문에 글자 그대로 있는지 볼 기준이라서."""
    text = value.strip()
    if has_forbidden_control(text):
        raise InvalidApplicationInput(CONTROL_CHAR_MESSAGE)
    if not text:
        raise InvalidApplicationInput("공고 본문을 붙여 넣어 주세요.")
    if len(text) > POSTING_TEXT_MAX_CHARS:
        raise InvalidApplicationInput(f"공고 본문은 {POSTING_TEXT_MAX_CHARS:,}자까지 붙여 넣을 수 있어요.")
    return text


def _clean_status(value: str) -> str:
    if value not in APPLICATION_STATUSES:
        raise InvalidApplicationInput("지원 상태 값이 틀렸어요.")
    return value


@dataclass(frozen=True)
class QuestionInput:
    text: str
    char_limit: int | None = None


def _clean_question(item: QuestionInput) -> QuestionInput | None:
    """문항 하나를 정리한다. 빈 문항은 None(부르는 쪽이 건너뛰거나 막음)."""
    text = item.text.strip()
    if has_forbidden_control(text):
        raise InvalidApplicationInput(CONTROL_CHAR_MESSAGE)
    if not text:
        return None
    if len(text) > APPLICATION_QUESTION_MAX_CHARS:
        raise InvalidApplicationInput(f"자소서 문항은 {APPLICATION_QUESTION_MAX_CHARS}자까지 쓸 수 있어요.")
    if item.char_limit is not None and not 1 <= item.char_limit <= APPLICATION_QUESTION_CHAR_LIMIT_MAX:
        raise InvalidApplicationInput(f"글자 수 제한은 1~{APPLICATION_QUESTION_CHAR_LIMIT_MAX:,}자로 적어 주세요.")
    return QuestionInput(text=text, char_limit=item.char_limit)


def _clean_questions(questions: list[QuestionInput]) -> list[QuestionInput]:
    if len(questions) > APPLICATION_MAX_QUESTIONS:
        raise InvalidApplicationInput(f"자소서 문항은 {APPLICATION_MAX_QUESTIONS}개까지 넣을 수 있어요.")
    # 빈 문항 줄은 건너뛴다(화면의 빈 입력칸)
    return [cleaned for item in questions if (cleaned := _clean_question(item)) is not None]


# --- 만들기 · 바꾸기 · 지우기 ---


def create_application(
    db: Session,
    *,
    user_id: int,
    company: str,
    role: str,
    deadline: date | None,
    url: str | None,
    posting_text: str,
    questions: list[QuestionInput],
    now: datetime | None = None,
) -> int:
    """공고 하나와 문항을 저장하고 번호를 돌려준다. 입력이 틀리면 InvalidApplicationInput(저장 안 함)."""
    at = now if now is not None else now_utc()
    application = Application(
        user_id=user_id,
        company=_one_line(company, label="회사 이름", max_chars=APPLICATION_COMPANY_MAX_CHARS),
        role=_one_line(role, label="직무", max_chars=APPLICATION_ROLE_MAX_CHARS),
        deadline=deadline,
        url=_clean_url(url),
        posting_text=_clean_posting(posting_text),
        status=APPLICATION_STATUS_DEFAULT,
        created_at=at,
        updated_at=at,
    )
    cleaned_questions = _clean_questions(questions)
    db.add(application)
    db.flush()
    for position, item in enumerate(cleaned_questions):
        db.add(
            ApplicationQuestion(
                user_id=user_id,
                application_id=application.id,
                position=position,
                text=item.text,
                char_limit=item.char_limit,
            )
        )
    db.commit()
    return application.id


def get_application_for_user(db: Session, *, user_id: int, application_id: int) -> Application | None:
    return db.scalar(select(Application).where(Application.id == application_id, Application.user_id == user_id))


_UNSET = object()


def update_application(
    db: Session,
    *,
    user_id: int,
    application_id: int,
    status: str | None = None,
    deadline: "date | None | object" = _UNSET,
    now: datetime | None = None,
) -> None:
    """상태 · 마감일만 바꾼다. deadline=None은 '마감일 지움', 안 주면 그대로."""
    application = get_application_for_user(db, user_id=user_id, application_id=application_id)
    if application is None:
        raise ApplicationNotFound
    if status is not None:
        application.status = _clean_status(status)
    if deadline is not _UNSET:
        application.deadline = deadline  # type: ignore[assignment]
    application.updated_at = now if now is not None else now_utc()
    db.commit()


@dataclass(frozen=True)
class QuestionEdit:
    """자소서 탭에서 고친 문항 하나. id가 있으면 기존 문항(초안 유지), 없으면 새 문항."""

    id: int | None
    text: str
    char_limit: int | None = None


def replace_questions(
    db: Session,
    *,
    user_id: int,
    application_id: int,
    questions: list[QuestionEdit],
    removed_ids: list[int] | None = None,
    now: datetime | None = None,
) -> None:
    """문항 목록을 통째로 저장한다(F-008 — 자소서 탭에서 추가 · 수정 · 삭제, 사용자 확인 2026-11-13).

    순서 = 목록 순서. 지울 문항은 화면이 removed_ids로 직접 보낸다 — 그 문항의 초안도 같이 지워진다(CASCADE, 화면이 확인창을 먼저 띄움).
    '보낸 문항 + 지울 문항'이 지금 공고의 문항과 정확히 같아야 저장한다. 다르면 다른 탭이 먼저 바꾼 것이라 QuestionsConflict —
    옛 목록을 가진 탭이 다른 탭에서 넣은 문항 · 초안을 모르고 지우지 않게(F-008 2차 리뷰 R2).
    공고 줄을 잠그고(PostgreSQL FOR UPDATE) 확인 · 저장해 두 요청이 사이에 끼어들지 않게 하고, 그래도 커밋에서 제약에 걸리면 409로 바꾼다.
    만들 때와 달리 빈 문항은 건너뛰지 않고 막는다 — 실수로 지운 글 때문에 초안이 사라지지 않게.
    ApplicationNotFound / QuestionsConflict / InvalidApplicationInput(저장 안 함).
    """
    application = db.scalar(
        select(Application).where(Application.id == application_id, Application.user_id == user_id).with_for_update()
    )
    if application is None:
        raise ApplicationNotFound
    if len(questions) > APPLICATION_MAX_QUESTIONS:
        raise InvalidApplicationInput(f"자소서 문항은 {APPLICATION_MAX_QUESTIONS}개까지 넣을 수 있어요.")
    cleaned: list[tuple[int | None, QuestionInput]] = []
    for item in questions:
        question = _clean_question(QuestionInput(text=item.text, char_limit=item.char_limit))
        if question is None:
            raise InvalidApplicationInput("빈 문항이 있어요. 문항을 적거나 지워 주세요.")
        cleaned.append((item.id, question))
    existing = {
        row.id: row
        for row in db.scalars(
            select(ApplicationQuestion).where(
                ApplicationQuestion.user_id == user_id, ApplicationQuestion.application_id == application.id
            )
        ).all()
    }
    given_ids = [question_id for question_id, _ in cleaned if question_id is not None]
    removed = set(removed_ids or [])
    if len(given_ids) != len(set(given_ids)) or removed & set(given_ids):
        raise InvalidApplicationInput("같은 문항이 두 번 들어 있어요. 새로고침한 뒤 다시 시도해 주세요.")
    if set(existing) != set(given_ids) | removed:
        db.rollback()  # 잠금을 바로 푼다
        raise QuestionsConflict
    if removed:
        db.execute(
            delete(ApplicationQuestion).where(
                ApplicationQuestion.user_id == user_id, ApplicationQuestion.id.in_(removed)
            )
        )
    # 순서 유니크(application_id, position)와 부딪히지 않게 남는 문항을 먼저 음수 자리로 옮긴 뒤 제자리에 놓는다
    for index, question_id in enumerate(given_ids):
        existing[question_id].position = -(index + 1)
    db.flush()
    for position, (question_id, question) in enumerate(cleaned):
        if question_id is None:
            db.add(
                ApplicationQuestion(
                    user_id=user_id,
                    application_id=application.id,
                    position=position,
                    text=question.text,
                    char_limit=question.char_limit,
                )
            )
        else:
            row = existing[question_id]
            row.position = position
            row.text = question.text
            row.char_limit = question.char_limit
    application.updated_at = now if now is not None else now_utc()
    try:
        db.commit()
    except (IntegrityError, StaleDataError) as exc:  # 잠금이 없는 DB(SQLite)에서 두 요청이 겹친 경우 등
        db.rollback()
        raise QuestionsConflict from exc


def delete_application(db: Session, *, user_id: int, application_id: int) -> None:
    """공고와 문항 · 역량 · 매칭 · 선점을 지운다(외래키 CASCADE). 평가 로그는 남는다."""
    removed = db.execute(
        delete(Application).where(Application.id == application_id, Application.user_id == user_id)
    ).rowcount
    if removed != 1:
        db.rollback()
        raise ApplicationNotFound
    db.commit()


# --- 목록 ---


@dataclass(frozen=True)
class ApplicationSummary:
    id: int
    company: str
    role: str
    deadline: date | None
    days_left: int | None  # 한국 날짜 기준 마감까지 남은 날(0 = 오늘 마감, 음수 = 지남). 마감일 없으면 None
    status: str
    url: str | None
    requirement_count: int
    matched_requirement_count: int  # 매칭 카드가 1장 이상인 역량 수
    extracted: bool
    matched: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ApplicationList:
    total: int
    applications: list[ApplicationSummary]


def _days_left(deadline: date | None, today: date) -> int | None:
    return (deadline - today).days if deadline is not None else None


def list_applications(db: Session, *, user_id: int, now: datetime | None = None) -> ApplicationList:
    today = korea_today(now)
    total = db.scalar(select(func.count()).select_from(Application).where(Application.user_id == user_id)) or 0
    # 묶음: 0 = 마감 남음(오늘 포함), 1 = 마감 지남, 2 = 마감일 없음
    group = case(
        (Application.deadline.is_(None), 2),
        (Application.deadline < today, 1),
        else_=0,
    )
    upcoming = case((Application.deadline >= today, Application.deadline))
    past = case((Application.deadline < today, Application.deadline))
    applications = db.scalars(
        select(Application)
        .where(Application.user_id == user_id)
        .order_by(group, upcoming.asc(), past.desc(), Application.created_at.desc(), Application.id.desc())
        .limit(MAX_APPLICATION_LIST)
    ).all()
    ids = [item.id for item in applications]
    requirement_counts: dict[int, int] = {}
    matched_counts: dict[int, int] = {}
    if ids:
        requirement_counts = dict(
            db.execute(
                select(PostingRequirement.application_id, func.count())
                .where(PostingRequirement.user_id == user_id, PostingRequirement.application_id.in_(ids))
                .group_by(PostingRequirement.application_id)
            ).all()
        )
        matched_counts = dict(
            db.execute(
                select(PostingRequirement.application_id, func.count(func.distinct(PostingRequirement.id)))
                .join(
                    RequirementMatch,
                    and_(
                        RequirementMatch.requirement_id == PostingRequirement.id,
                        RequirementMatch.user_id == user_id,
                    ),
                )
                .where(PostingRequirement.user_id == user_id, PostingRequirement.application_id.in_(ids))
                .group_by(PostingRequirement.application_id)
            ).all()
        )
    return ApplicationList(
        total=total,
        applications=[
            ApplicationSummary(
                id=item.id,
                company=item.company,
                role=item.role,
                deadline=item.deadline,
                days_left=_days_left(item.deadline, today),
                status=item.status,
                url=item.url,
                requirement_count=requirement_counts.get(item.id, 0),
                matched_requirement_count=matched_counts.get(item.id, 0),
                extracted=item.extracted_at is not None,
                matched=item.matched_at is not None,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
            for item in applications
        ],
    )


# --- 상세 ---


@dataclass(frozen=True)
class QuestionDetail:
    id: int
    position: int
    text: str
    char_limit: int | None


@dataclass(frozen=True)
class MatchDetail:
    id: int
    card_id: int
    card_title: str
    slot: str
    quote: str
    quote_source: str
    quote_start: int
    quote_end: int
    reason: str


@dataclass(frozen=True)
class RequirementDetail:
    id: int
    position: int
    name: str
    kind: str
    quote: str
    quote_start: int
    quote_end: int
    matches: list[MatchDetail] = field(default_factory=list)


@dataclass(frozen=True)
class ApplicationDetail:
    id: int
    company: str
    role: str
    deadline: date | None
    days_left: int | None
    url: str | None
    posting_text: str
    status: str
    extracted_at: datetime | None
    matched_at: datetime | None
    created_at: datetime
    updated_at: datetime
    questions: list[QuestionDetail]
    requirements: list[RequirementDetail]


def get_application_detail(
    db: Session, *, user_id: int, application_id: int, now: datetime | None = None
) -> ApplicationDetail:
    application = get_application_for_user(db, user_id=user_id, application_id=application_id)
    if application is None:
        raise ApplicationNotFound
    questions = db.scalars(
        select(ApplicationQuestion)
        .where(ApplicationQuestion.user_id == user_id, ApplicationQuestion.application_id == application.id)
        .order_by(ApplicationQuestion.position)
    ).all()
    requirements = db.scalars(
        select(PostingRequirement)
        .where(PostingRequirement.user_id == user_id, PostingRequirement.application_id == application.id)
        .order_by(PostingRequirement.position)
    ).all()
    matches_by_requirement: dict[int, list[MatchDetail]] = {}
    if requirements:
        rows = db.execute(
            select(RequirementMatch, Card.title)
            .join(Card, and_(Card.id == RequirementMatch.card_id, Card.user_id == user_id))
            .where(
                RequirementMatch.user_id == user_id,
                RequirementMatch.requirement_id.in_([item.id for item in requirements]),
            )
            .order_by(RequirementMatch.id)
        ).all()
        for match, card_title in rows:
            matches_by_requirement.setdefault(match.requirement_id, []).append(
                MatchDetail(
                    id=match.id,
                    card_id=match.card_id,
                    card_title=card_title,
                    slot=match.slot,
                    quote=match.quote,
                    quote_source=match.quote_source,
                    quote_start=match.quote_start,
                    quote_end=match.quote_end,
                    reason=match.reason,
                )
            )
    return ApplicationDetail(
        id=application.id,
        company=application.company,
        role=application.role,
        deadline=application.deadline,
        days_left=_days_left(application.deadline, korea_today(now)),
        url=application.url,
        posting_text=application.posting_text,
        status=application.status,
        extracted_at=application.extracted_at,
        matched_at=application.matched_at,
        created_at=application.created_at,
        updated_at=application.updated_at,
        questions=[
            QuestionDetail(id=item.id, position=item.position, text=item.text, char_limit=item.char_limit)
            for item in questions
        ],
        requirements=[
            RequirementDetail(
                id=item.id,
                position=item.position,
                name=item.name,
                kind=item.kind,
                quote=item.quote,
                quote_start=item.quote_start,
                quote_end=item.quote_end,
                matches=matches_by_requirement.get(item.id, []),
            )
            for item in requirements
        ],
    )
