"""노트를 조각으로 나누기 (F-002 설계 의도, 사용자 확인).

규칙
1. 제목(# ~ ###) 기준으로 구역을 나눈다. 코드 블록 안의 "# 주석"은 제목이 아니다. ####부터는 나누지 않는다.
2. 한 구역이 기준 길이(CHUNK_MAX_CHARS)를 넘으면 문단(빈 줄) 경계에서 다시 자른다.
   문단 하나가 기준보다 길면 줄 경계에서, 줄 하나가 기준보다 길면 기준 길이에서 자른다.
3. 조각은 원문의 한 구간이다: content == 원문[start_offset:end_offset] (앞뒤 공백은 구간에서 뺀다).
4. 제목 줄만 있고 본문이 없는 구역은 조각으로 만들지 않는다(하위 제목의 경로에 이미 들어 있음).

조각마다 제목 경로("# React > ## useEffect")를 붙여, 근거를 "어느 제목 아래"로 보여 줄 수 있게 한다(설계 원칙 1).
경로에 넣는 제목 한 단계는 HEADING_PATH_TEXT_MAX_CHARS에서 자른다(긴 제목이 조각마다 복사돼 메모리가 터지는 것을 막음).

메모리: 줄 · 구역을 목록에 모아 두지 않고 위치(시작 · 끝)만 들고 흘려보낸다. 그래서 줄이 아주 많은 파일도
쓰는 메모리가 줄 수가 아니라 조각 수에 비례한다(F-002 3차 R2 — 줄 100만 개짜리 1MB 파일이 180MB를 쓰던 것).
구역은 늘 코드 블록 밖에서 시작하므로(제목 줄 또는 문서 맨 앞), 긴 구역을 다시 훑을 때 코드 블록 상태를 처음부터 시작해도 된다.

줄 단위 읽기(markdown_lines · parse_heading)는 지금 마크다운 어댑터 파일에 있다. 노션 어댑터(4주차)를 붙일 때
공용 위치로 옮길지 정한다(F-002 1차 R1-2, 사용자 확인).
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from app.config import CHUNK_MAX_CHARS, HEADING_PATH_TEXT_MAX_CHARS
from app.importers.markdown import markdown_lines, parse_heading

SPLIT_HEADING_MAX_LEVEL = 3
HEADING_PATH_SEPARATOR = " > "
TRUNCATED_MARK = "…"


def _path_label(level: int, text: str) -> str:
    if len(text) > HEADING_PATH_TEXT_MAX_CHARS:
        text = text[:HEADING_PATH_TEXT_MAX_CHARS] + TRUNCATED_MARK
    return f"{'#' * level} {text}"


@dataclass(frozen=True)
class ChunkDraft:
    """저장 전 조각. 위치는 노트 원문 기준 파이썬 문자 단위."""

    heading_path: str
    start_offset: int
    end_offset: int
    content: str


@dataclass(frozen=True)
class _Section:
    """제목 하나 아래의 구간. 줄 목록 대신 위치만 든다."""

    heading_path: str
    start: int
    end: int
    has_body: bool  # 제목 줄 말고 글이 있는 줄이 하나라도 있나


class TooManyChunksError(ValueError):
    """조각이 max_chunks를 넘었다. 넘는 순간 멈추므로 나머지 원문은 나누지 않는다."""


def _sections(content: str) -> Iterator[_Section]:
    """제목(1~3단계)이 나올 때마다 앞 구역을 내보내고 새 구역을 연다. 첫 제목 앞의 글은 경로가 빈 구역."""
    stack: list[tuple[int, str]] = []  # (단계, "## 글")
    path = ""
    start: int | None = None
    end = 0
    has_body = False
    for line in markdown_lines(content):
        heading = parse_heading(line)
        if heading is not None and heading[0] <= SPLIT_HEADING_MAX_LEVEL:
            if start is not None:
                yield _Section(heading_path=path, start=start, end=end, has_body=has_body)
            level, text = heading
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, _path_label(level, text)))
            path = HEADING_PATH_SEPARATOR.join(label for _, label in stack)
            start, end, has_body = line.start, line.end, False
            continue
        if start is None:
            start = line.start
        end = line.end
        if line.text.strip():
            has_body = True
    if start is not None:
        yield _Section(heading_path=path, start=start, end=end, has_body=has_body)


def _trimmed(content: str, start: int, end: int) -> tuple[int, int]:
    """구간 앞뒤의 공백 · 줄바꿈을 뺀 구간."""
    while start < end and content[start].isspace():
        start += 1
    while end > start and content[end - 1].isspace():
        end -= 1
    return start, end


def _line_units(start: int, end: int, max_chars: int) -> Iterator[tuple[int, int]]:
    """줄 하나. 기준보다 길면 기준 길이씩 자른다."""
    if end - start <= max_chars:
        yield start, end
        return
    for piece_start in range(start, end, max_chars):
        yield piece_start, min(piece_start + max_chars, end)


def _units(content: str, start: int, end: int, max_chars: int) -> Iterator[tuple[int, int]]:
    """구간을 기준 길이를 넘지 않는 덩어리로 흘려보낸다: 문단 → (길면) 줄 → (길면) 기준 길이 조각.

    문단이 기준 길이 안일 동안만 그 문단의 줄 위치를 모아 둔다(최대 기준 길이만큼). 넘는 순간 모아 둔 줄을
    내보내고, 그 문단의 나머지 줄은 바로바로 내보낸다. 그래서 문단이 아무리 길어도 모아 두는 양이 작다.
    """
    pending: list[tuple[int, int]] = []
    paragraph_start: int | None = None
    paragraph_end = 0
    oversized = False
    for line in markdown_lines(content, start, end):
        if not line.in_code and not line.text.strip():  # 빈 줄(코드 블록 밖) = 문단 경계
            if paragraph_start is not None and not oversized:
                yield paragraph_start, paragraph_end
            paragraph_start, pending, oversized = None, [], False
            continue
        if paragraph_start is None:
            paragraph_start = line.start
        paragraph_end = line.end
        if oversized:
            yield from _line_units(line.start, line.end, max_chars)
            continue
        pending.append((line.start, line.end))
        if paragraph_end - paragraph_start > max_chars:
            oversized = True
            for line_start, line_end in pending:
                yield from _line_units(line_start, line_end, max_chars)
            pending = []
    if paragraph_start is not None and not oversized:
        yield paragraph_start, paragraph_end


def _pack(units: Iterable[tuple[int, int]], max_chars: int) -> Iterator[tuple[int, int]]:
    """앞에서부터 덩어리를 이어 붙이다가, 기준 길이를 넘기기 직전에 조각을 끊는다."""
    piece_start: int | None = None
    piece_end = 0
    for start, end in units:
        if piece_start is None:
            piece_start, piece_end = start, end
        elif end - piece_start <= max_chars:
            piece_end = end
        else:
            yield piece_start, piece_end
            piece_start, piece_end = start, end
    if piece_start is not None:
        yield piece_start, piece_end


def split_markdown(
    content: str, max_chars: int = CHUNK_MAX_CHARS, max_chunks: int | None = None
) -> list[ChunkDraft]:
    """노트 원문을 조각 목록으로 나눈다. 순서는 원문 순서.

    max_chunks를 주면 조각이 그보다 많아지는 순간 TooManyChunksError로 멈춘다(상한을 넘을 파일을 끝까지 나누지 않게).
    """
    drafts: list[ChunkDraft] = []
    for section in _sections(content):
        if not section.has_body:
            continue  # 제목만 있는 구역(규칙 4) 또는 빈 구역

        section_start, section_end = _trimmed(content, section.start, section.end)
        if section_end - section_start <= max_chars:
            spans: Iterable[tuple[int, int]] = [(section_start, section_end)]
        else:
            spans = _pack(_units(content, section.start, section.end, max_chars), max_chars)

        for raw_start, raw_end in spans:
            start, end = _trimmed(content, raw_start, raw_end)
            if start >= end:
                continue
            if max_chunks is not None and len(drafts) >= max_chunks:
                raise TooManyChunksError(f"조각이 {max_chunks}개를 넘어요.")
            drafts.append(
                ChunkDraft(
                    heading_path=section.heading_path,
                    start_offset=start,
                    end_offset=end,
                    content=content[start:end],
                )
            )
    return drafts
