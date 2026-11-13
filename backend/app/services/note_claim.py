"""AI 작업 선점 — AI를 오래 부르는 기능(문제 만들기 · 카드 후보 찾기 · 공고 분석)이 같이 쓰는 동시 클릭 막기 (F-004 · F-006 · F-007).

선점 대상(target)은 기능마다 다르다 — 퀴즈 · 카드는 노트(note_id), 공고 분석은 공고(application_id). ClaimTable.key가 그 칸 이름이다.

규칙 (모든 AI 기능이 똑같이 따른다 — F-006 1차 리뷰 R1에서 한 곳으로 모음, 사용자 확인 2026-11-11)
- 대상(노트 · 공고)마다 선점은 기능별로 하나만(선점 표의 대상 칸 유니크).
- 사용자당 진행 중인 AI 작업은 기능을 가리지 않고 하나만(D-020, 사용자 확인 2026-11-11) — 요청마다 작업 스레드를
  최대 180초 붙잡아서. 퀴즈를 만드는 중에 카드 후보 찾기를 누르면 409. 새 AI 기능은 ALL_TABLES에 선점 표를 더한다.
- 사용자 줄을 잠그고(PostgreSQL FOR NO KEY UPDATE — 같은 사용자의 선점을 차례로 세움) 그 잠금 안에서
  "다른 AI 작업이 진행 중인가 → 이 대상의 선점이 없으면 새로, 끝났으면 '이미 함', 5분 지났으면 가져가고,
  진행 중이면 409"를 모두 정한 뒤 한 번만 커밋한다. 커밋 · rollback 전까지 잠금이 남아 두 요청이 사이에 끼어들 수 없다
  (F-004 2차 리뷰 R2 — 전에는 유니크 충돌 rollback이 잠금을 먼저 풀어 오래된 선점 경로가 잠금 밖이었다).
- FOR NO KEY UPDATE는 이 잠금끼리만 막고, 같은 사용자 줄을 가리키는 외래키 INSERT(사용량 · 풀이 기록)는 막지 않는다.
- SQLite(테스트)는 줄 잠금이 없어서 대상 칸 유니크 제약이 같은 대상의 동시 선점을 막는 안전망이 된다.
- 전제: 격리 수준 READ COMMITTED(PostgreSQL 기본값, 엔진은 따로 정하지 않음). 잠금을 얻은 뒤의 SELECT가 새 스냅숏으로
  앞 요청이 커밋한 선점을 봐야 한다. REPEATABLE READ로 바꾸면 다른 노트 두 개가 함께 통과할 수 있다(F-004 3차 리뷰 R2).
- 선점의 주인: 선점한 시각(claimed_at)이 그 요청의 표시다. 해제 · 끝내기는 "내가 잡은 시각 그대로일 때만" 한다 —
  오래된 선점을 다른 요청이 가져간 뒤 원래 요청이 늦게 끝나도 남의 선점을 지우거나 끝내지 않게(F-006 1차 리뷰 R2).

기능마다 다른 점은 ClaimTable로 받는다 — '끝남'을 무엇으로 보는지.
- 퀴즈: 그 노트에 문제가 있으면 끝남. 성공한 선점은 그대로 남고, 이미 문제가 있는 노트는 선점 전에 409로 막는다.
- 카드: 선점의 finished_at이 있으면 끝남. 후보는 버릴 수 있어서 카드 유무로는 알 수 없기 때문이다(F-006).
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, Delete, delete, exists, false, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import APPLICATION_CLAIM_STALE_SECONDS, CARD_CLAIM_STALE_SECONDS, QUIZ_CLAIM_STALE_SECONDS
from app.db.models import ApplicationClaim, NoteCardClaim, NoteQuizClaim, Quiz, User

logger = logging.getLogger(__name__)

ClaimModel = type[NoteQuizClaim] | type[NoteCardClaim] | type[ApplicationClaim]


class OtherAIWorkInProgress(Exception):
    """같은 사용자의 다른 AI 작업(다른 노트 · 공고 · 다른 기능)이 진행 중이다(D-020). AI를 부르지 않는다.

    요청마다 작업 스레드를 최대 180초 붙잡으므로, 한 사용자가 여러 작업을 동시에 보내 서버를 붙잡지 못하게 한다.
    모든 AI 기능이 같은 예외를 쓴다(F-006 2차 리뷰 R1).
    """


class ClaimLost(Exception):
    """저장하려는데 내 선점이 없다(다른 요청이 오래된 선점으로 보고 가져감). 결과를 저장하지 않는다(F-006 1 · 2차 리뷰 R2)."""


@dataclass(frozen=True)
class ClaimTable:
    """AI 기능 하나의 선점 표."""

    model: ClaimModel
    stale_seconds: int  # 이보다 오래된 진행 중 선점은 새 요청이 가져간다(서버가 도중에 죽은 경우)
    finished: Callable[[int], ColumnElement[bool]]  # user_id → "이 선점 줄은 끝났다" SQL 조건(선점 표 줄 기준)
    keeps_finished: bool  # 끝난 선점을 '이미 함' 표시로 남겨 두는가(카드). False면 이 대상의 선점에서 끝남을 보지 않는다(퀴즈 · 공고)
    key: str = "note_id"  # 선점 대상 칸 이름(유니크). 공고 분석은 "application_id"


def _key(table: ClaimTable) -> ColumnElement[int]:
    return getattr(table.model, table.key)


QUIZ_CLAIMS = ClaimTable(
    model=NoteQuizClaim,
    stale_seconds=QUIZ_CLAIM_STALE_SECONDS,
    finished=lambda user_id: exists().where(Quiz.user_id == user_id, Quiz.note_id == NoteQuizClaim.note_id),
    keeps_finished=False,
)
CARD_CLAIMS = ClaimTable(
    model=NoteCardClaim,
    stale_seconds=CARD_CLAIM_STALE_SECONDS,
    finished=lambda _user_id: NoteCardClaim.finished_at.is_not(None),
    keeps_finished=True,
)
# 공고 분석(F-007): ① 역량 뽑기 · ② 매칭이 공고 하나의 선점 한 줄을 같이 쓴다(둘이 동시에 돌지 않게).
# 끝나면 성공 · 실패 모두 선점을 지운다 — '이미 뽑음'은 applications.extracted_at으로 본다(② 매칭은 몇 번이든).
APPLICATION_CLAIMS = ClaimTable(
    model=ApplicationClaim,
    stale_seconds=APPLICATION_CLAIM_STALE_SECONDS,
    finished=lambda _user_id: false(),
    keeps_finished=False,
    key="application_id",
)
ALL_TABLES = (QUIZ_CLAIMS, CARD_CLAIMS, APPLICATION_CLAIMS)  # 사용자당 AI 작업 1개를 셀 때 보는 표 전부


@dataclass(frozen=True)
class ClaimRules:
    table: ClaimTable
    in_progress: type[Exception]  # 이 대상(노트 · 공고)을 다른 요청이 하는 중
    already_done: type[Exception] | None  # 이 대상은 이미 끝남(keeps_finished일 때만)
    label: str  # 로그에 쓰는 기능 이름


def _active_elsewhere(table: ClaimTable, *, user_id: int, at: datetime, except_target_id: int | None) -> ColumnElement[bool]:
    """이 표에 같은 사용자의 진행 중인 선점이 있는가(except_target_id는 빼고)."""
    model = table.model
    conditions = [
        model.user_id == user_id,
        model.claimed_at >= at - timedelta(seconds=table.stale_seconds),
        ~table.finished(user_id),
    ]
    if except_target_id is not None:
        conditions.append(_key(table) != except_target_id)
    return exists().where(*conditions)


def claim_target(db: Session, rules: ClaimRules, *, user_id: int, target_id: int, at: datetime) -> datetime:
    """대상(노트 · 공고 — rules.table.key)을 선점하고 선점 시각(이 요청의 표시)을 돌려준다.

    못 하면 rules의 예외를 올린다(그 전에 rollback으로 잠금을 푼다). 파일 이름(note_claim)은 노트에서 시작해서 남은 것이다.
    """
    table = rules.table
    model = table.model
    stale_before = at - timedelta(seconds=table.stale_seconds)
    db.execute(select(User.id).where(User.id == user_id).with_for_update(key_share=True))
    busy = db.scalar(
        select(
            or_(
                *(
                    _active_elsewhere(other, user_id=user_id, at=at, except_target_id=target_id if other is table else None)
                    for other in ALL_TABLES
                )
            )
        )
    )
    if busy:
        db.rollback()
        raise OtherAIWorkInProgress

    # 이 대상의 선점: (끝남?, 오래됨?) — 비교는 DB에서(시간대 표기가 DB마다 달라서)
    finished = table.finished(user_id) if table.keeps_finished else false()
    row = db.execute(
        select(finished, model.claimed_at < stale_before).where(_key(table) == target_id, model.user_id == user_id)
    ).first()
    if row is None:
        db.add(model(user_id=user_id, claimed_at=at, **{table.key: target_id}))
    elif row[0]:
        db.rollback()
        raise rules.already_done or rules.in_progress
    elif row[1]:
        # 읽은 뒤 잠금 밖의 해제(DELETE)가 끼어들 수 있어서 "아직 오래된 진행 중 선점일 때만" 바꾸고 바뀐 줄을 센다(F-004 3차 리뷰 R2)
        conditions = [_key(table) == target_id, model.user_id == user_id, model.claimed_at < stale_before]
        if table.keeps_finished:
            conditions.append(~table.finished(user_id))
        taken = db.execute(update(model).where(*conditions).values(claimed_at=at)).rowcount
        if taken != 1:
            db.rollback()
            raise rules.in_progress
        logger.warning("오래된 %s 선점을 가져감 user_id=%s target_id=%s", rules.label, user_id, target_id)
    else:
        db.rollback()
        raise rules.in_progress
    try:
        db.commit()
    except IntegrityError:  # 줄 잠금이 없는 DB에서 같은 대상을 동시에 선점한 경우(유니크 제약이 막음)
        db.rollback()
        raise rules.in_progress from None
    return at


def ensure_still_owned(
    db: Session,
    rules: ClaimRules,
    *,
    user_id: int,
    target_id: int,
    claimed_at: datetime,
    finished_at: datetime | None = None,
) -> None:
    """저장 트랜잭션 안에서 내 선점이 아직 내 것인지 확인한다(줄을 건드려 잠금 — 가져가기 UPDATE와 차례로).

    finished_at을 주면 '끝남'으로 표시하고(카드 — 이미 찾은 노트), 안 주면 선점 시각을 같은 값으로 다시 쓴다
    (퀴즈 — 성공한 선점은 그대로 남김). 바뀐 줄이 1이 아니면 ClaimLost — 부르는 쪽이 rollback하고 결과를 저장하지 않는다.
    """
    model = rules.table.model
    changes = {"finished_at": finished_at} if finished_at is not None else {"claimed_at": claimed_at}
    owned = owned_by(rules, user_id=user_id, target_id=target_id, claimed_at=claimed_at)
    if db.execute(update(model).where(*owned).values(**changes)).rowcount != 1:
        raise ClaimLost


def owned_by(rules: ClaimRules, *, user_id: int, target_id: int, claimed_at: datetime) -> list[ColumnElement[bool]]:
    """'내가 잡은 그 선점' 조건 — 해제 · 끝내기에 쓴다."""
    model = rules.table.model
    return [_key(rules.table) == target_id, model.user_id == user_id, model.claimed_at == claimed_at]


def release_statement(rules: ClaimRules, *, user_id: int, target_id: int, claimed_at: datetime) -> Delete:
    """내 선점을 지우는 문장(커밋은 부르는 쪽). 끝난 선점을 남기는 기능이면 진행 중인 선점만 지운다."""
    table = rules.table
    statement = delete(table.model).where(*owned_by(rules, user_id=user_id, target_id=target_id, claimed_at=claimed_at))
    if table.keeps_finished:
        statement = statement.where(~table.finished(user_id))
    return statement


def release_claim(db: Session, rules: ClaimRules, *, user_id: int, target_id: int, claimed_at: datetime) -> None:
    """내 선점을 지운다(다시 누를 수 있게). 실패해도 5분 뒤 풀리므로 오류를 올리지 않는다."""
    try:
        db.execute(release_statement(rules, user_id=user_id, target_id=target_id, claimed_at=claimed_at))
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("%s 선점 해제 실패 user_id=%s error=%s", rules.label, user_id, type(exc).__name__)
