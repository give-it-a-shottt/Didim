"""'확인 필요' 규칙 (D-028) — 근거가 붙은 문장에 인용 밖 사실이 덧붙었는지 AI 없이 의심한다.

R1 카드(제목 · 모든 칸)에 없는 숫자 · 영문 낱말, R3 결과 칸이 빈 카드에 성과 표현.
2026-11-16 NVIDIA 초안 평가에서 근거 검사를 통과한 '지어냄' 4문장을 그대로 회귀 사례로 둔다(3개 잡음 · 1개는 알려진 한계).
"""

import pytest

from app.services.claim_check import (
    CLAIM_RESULT_WITHOUT_RECORD,
    CLAIM_UNKNOWN_TOKEN,
    CardFacts,
    ClaimCheck,
    check_claims,
    numbers_in,
    words_in,
)


def check(sentence: str, card_texts: list[str], *, result_recorded: bool) -> ClaimCheck:
    return check_claims(sentence, CardFacts.of(card_texts, result_recorded=result_recorded))

# eval/cards/notes c06-2(GitHub Actions 빌드 시간) — 결과 칸이 비어 있는 카드
C06_2 = [
    "GitHub Actions 빌드 시간",
    "PR마다 도는 CI가 매번 의존성을 처음부터 설치해서 8분씩 걸렸다. 리뷰를 요청하기 전에 CI가 끝나길 기다리는 시간이 아까웠다.",
    "actions/cache로 패키지 캐시를 잠금 파일 해시 기준으로 저장하게 바꿨다.",
]
# c07-2(해커톤 시연 모드) — 결과 칸이 있는 카드
C07_2 = [
    "해커톤 시연",
    "발표 전날 밤 리허설에서 학교 와이파이가 끊겨 API 호출이 모두 실패했다.",
    "API 응답 몇 개를 JSON 파일로 저장해 두고, 네트워크가 안 되면 그 파일로 화면을 그리는 시연 모드를 새벽 3시까지 만들었다.",
    "본 발표 중에 실제로 와이파이가 한 번 끊겼지만 시연 모드로 넘어가 끝까지 시연했고, 팀은 장려상을 받았다.",
]


def test_tokens_are_numbers_and_latin_words() -> None:
    assert numbers_in("1,200개 중 3.5초, 40%") == {"1200", "3.5", "40"}
    assert words_in("N+1 문제를 SQLAlchemy로, C#도") == {"n+1", "sqlalchemy", "c#"}


def test_number_or_word_missing_from_the_whole_card_is_flagged() -> None:
    result = check("캐시를 넣어 37% 빨라졌고 Kubernetes에도 올렸습니다.", C07_2, result_recorded=True)
    assert result.reasons == [CLAIM_UNKNOWN_TOKEN]
    assert result.unknown_tokens == ["37", "kubernetes"]


def test_tokens_from_other_fields_of_the_same_card_pass() -> None:
    """같은 카드의 다른 칸(상황 · 결과)에 있는 숫자 · 낱말은 통과 — 진짜 문장도 칸을 섞어 쓴다(R2를 버린 이유)."""
    result = check(
        "새벽 3시까지 JSON 시연 모드를 만들어 API 장애에도 끝까지 시연했습니다.", C07_2, result_recorded=True
    )
    assert result.flagged is False
    assert check("3과 30은 다르다", ["30분"], result_recorded=True).unknown_tokens == ["3"]


@pytest.mark.parametrize(
    "sentence",
    [
        "GitHub Actions에서 의존성 캐시를 잠금 파일 해시 기준으로 적용해 CI 빌드 시간을 8분에서 크게 줄였습니다.",
        "PR마다 8분 걸리던 CI 빌드를 actions/cache로 패키지 캐시를 잠금 파일 해시 기준으로 저장해 빌드 시간을 단축했습니다.",
        "GitHub Actions에 패키지 캐시를 도입해 의존성 설치 시간을 8분에서 캐시 히트 시 대폭 단축했습니다.",
    ],
)
def test_real_ai_sentences_adding_a_result_to_an_unrecorded_card_are_flagged(sentence: str) -> None:
    """2026-11-16 평가에서 근거 검사를 통과한 지어냄 3개(c06-2 결과 지어냄) — 숫자 · 낱말은 모두 카드에 있어 R1로는 못 잡는다."""
    result = check(sentence, C06_2, result_recorded=False)
    assert result.reasons == [CLAIM_RESULT_WITHOUT_RECORD]


def test_context_change_is_a_known_limit() -> None:
    """'팀 해커톤'을 '개인 프로젝트'로 바꾼 문장은 숫자 · 영문 · 성과 표현이 없어 규칙으로 못 잡는다(D-028 알려진 한계)."""
    sentence = "개인 프로젝트에서 네트워크 장애 발생 시 API 응답을 로컬 JSON 파일로 저장하고 화면을 그리는 대체 경로를 구현했습니다."
    assert check(sentence, C07_2, result_recorded=True).flagged is False


@pytest.mark.parametrize(
    "sentence",
    [
        "CI 빌드 시간을 줄이기 위해 actions/cache로 패키지 캐시를 저장하게 바꿨습니다.",  # 목적(줄이기 위해)은 성과가 아님
        "actions/cache로 패키지 캐시를 잠금 파일 해시 기준으로 저장하게 바꿨습니다.",
    ],
)
def test_action_or_purpose_without_a_result_claim_passes(sentence: str) -> None:
    assert check(sentence, C06_2, result_recorded=False).flagged is False


def test_result_expression_passes_when_the_result_is_recorded() -> None:
    sentence = "시연 모드 덕분에 와이파이가 끊겨도 끝까지 시연해 장애를 해결했습니다."
    assert check(sentence, C07_2, result_recorded=True).flagged is False
    assert check(sentence, C07_2, result_recorded=False).reasons == [CLAIM_RESULT_WITHOUT_RECORD]


@pytest.mark.parametrize(
    "sentence",
    [
        "리프레시 요청이 동시에 여러 번 나가지 않도록 진행 중인 요청을 공유해 동시 요청을 방지했습니다.",
        "actions/cache를 이용해 패키지 캐시를 잠금 파일 해시 기준으로 저장하도록 개선했습니다.",
    ],
)
def test_action_words_prevent_and_improve_are_not_result_claims(sentence: str) -> None:
    """'방지했' · '개선했'은 행동 설명에도 써서 목록에서 뺐다 — 2회차 평가의 잘못 경고(사용자 선택 2026-11-17)."""
    assert check(sentence, C06_2 + ["리프레시 요청이 동시에 여러 번 나가지 않도록 진행 중인 요청 하나를 공유하게 했다."], result_recorded=False).flagged is False


def test_key_names_reasons_and_tokens_for_confirmation() -> None:
    """[확인함] 때 저장하는 이유 — 숫자가 바뀌거나 이유가 늘면 다른 값이 돼 확인이 풀린다(Q-029)."""
    both = check("캐시로 37% 단축했습니다.", C06_2, result_recorded=False)
    assert both.key == "unknown_token:37|result_without_record"
    assert check("캐시로 40% 단축했습니다.", C06_2, result_recorded=False).key != both.key
    assert check("캐시로 빌드를 단축했습니다.", C06_2, result_recorded=False).key == "result_without_record"
    assert check("캐시를 저장하게 바꿨습니다.", C06_2, result_recorded=False).key == ""
