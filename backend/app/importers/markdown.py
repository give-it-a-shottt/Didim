"""마크다운 파일 어댑터 (D-001, F-002).

파일 이름 · 바이트를 받아 ImportedDocument로 바꾼다. 읽을 수 없으면 이유를 담은 UnreadableFileError.
제목 · 코드 블록을 알아보는 줄 단위 읽기(markdown_lines · parse_heading)도 여기 두고, 나누기(app/services/chunking.py)가 같이 쓴다.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath

from app.config import BYTES_PER_MB, MAX_IMPORT_FILE_BYTES, NOTE_TITLE_MAX_CHARS
from app.importers.base import ImportedDocument, UnreadableFileError

MARKDOWN_SUFFIXES = frozenset({".md", ".markdown"})
SOURCE_MARKDOWN = "markdown"
FILENAME_MAX_CHARS = 255
UNNAMED_FILE = "이름 없는 파일"

# ATX 제목: 줄 앞 공백 0~3칸 + # 1~6개 + 공백 + 나머지 전부.
# 닫는 # · 끝 공백은 정규식이 아니라 _strip_closing_hashes가 뗀다. 정규식에 "게으른 반복 + 끝 공백 반복"을 같이 두면
# 공백이 긴 줄에서 시간이 제곱으로 늘어난다(ReDoS, F-002 1차 R2 — 공백 1만6천 개에 1.5초).
_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*)$")
# 코드 블록 시작(``` 또는 ~~~ 3개 이상, 뒤에 언어 이름 등이 올 수 있음). 코드 안의 "# 주석"을 제목으로 읽지 않으려고 따라간다.
_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})")
# 코드 블록 끝: 같은 기호만 있고 뒤에 글이 없어야 한다(```js 같은 줄은 블록을 닫지 않음, CommonMark).
_FENCE_CLOSE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")


def _strip_closing_hashes(text: str) -> str:
    """제목 끝의 공백과 닫는 # 묶음을 뗀다. # 묶음 앞이 공백일 때만 닫는 표시로 본다("C#"은 그대로)."""
    text = text.rstrip(" \t")
    without_hashes = text.rstrip("#")
    if without_hashes != text and (without_hashes == "" or without_hashes[-1] in " \t"):
        return without_hashes.rstrip(" \t")
    return text


_FENCE_CHARACTERS = ("`", "~")


@dataclass(frozen=True, slots=True)
class MarkdownLine:
    """원문의 한 줄. start · end는 원문 위치(end는 줄바꿈 포함), text는 줄바꿈을 뺀 내용."""

    start: int
    end: int
    text: str
    in_code: bool  # 코드 블록 안이거나 코드 블록 시작 · 끝 줄


def markdown_lines(content: str, start: int = 0, end: int | None = None) -> Iterator[MarkdownLine]:
    """원문의 [start:end] 구간을 줄로 나누고, 줄마다 코드 블록 안인지 표시한다(코드 블록 상태는 start에서 새로 시작).

    줄 목록을 한꺼번에 만들지 않고 한 줄씩 내보낸다. 쓰는 쪽이 중간에 멈출 수 있고, 줄이 아주 많아도 메모리를 덜 쓴다.
    줄바꿈은 \\n만 본다(읽을 때 \\r\\n · \\r을 \\n으로 맞춰 둠).
    """
    stop = len(content) if end is None else end
    fence: str | None = None
    position = start
    while position < stop:
        newline = content.find("\n", position, stop)
        line_end = stop if newline == -1 else newline + 1
        text = content[position : line_end if newline == -1 else newline]
        if fence is None:
            opening = _FENCE_OPEN.match(text) if text.lstrip(" ").startswith(_FENCE_CHARACTERS) else None
            if opening:
                fence = opening.group(1)
            in_code = opening is not None
        else:
            closing = _FENCE_CLOSE.match(text)
            if closing and closing.group(1)[0] == fence[0] and len(closing.group(1)) >= len(fence):
                fence = None
            in_code = True  # 블록 안의 줄과 닫는 줄 모두 코드
        yield MarkdownLine(start=position, end=line_end, text=text, in_code=in_code)
        position = line_end


def parse_heading(line: MarkdownLine) -> tuple[int, str] | None:
    """제목 줄이면 (단계, 글), 아니면 None. 코드 블록 안은 제목이 아니다."""
    if line.in_code or not line.text.lstrip(" ").startswith("#"):
        return None  # 대부분의 줄은 여기서 바로 끝난다(정규식을 돌리지 않음)
    match = _HEADING.match(line.text)
    if match is None:
        return None
    text = _strip_closing_hashes(match.group(2)).strip()
    if not text:
        return None  # "# " · "## ##"처럼 글이 없는 제목은 제목으로 보지 않는다
    return len(match.group(1)), text


def find_title(content: str) -> str | None:
    """코드 블록 밖의 첫 `# 제목`(1단계). 없으면 None."""
    for line in markdown_lines(content):
        heading = parse_heading(line)
        if heading is not None and heading[0] == 1:
            return heading[1]
    return None


def clean_filename(raw_name: str | None) -> str:
    """브라우저가 보낸 파일 이름에서 폴더 부분을 떼고 길이를 자른다. 화면 표시 · 오류 안내용."""
    name = PurePosixPath((raw_name or "").replace("\\", "/")).name.strip()
    return name[:FILENAME_MAX_CHARS] or UNNAMED_FILE


def normalize_newlines(text: str) -> str:
    """윈도우(\\r\\n) · 옛 맥(\\r) 줄바꿈을 \\n으로 맞춘다. 같은 글이면 같은 해시가 나오게(중복 확인)."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def read_markdown_file(filename: str, data: bytes) -> ImportedDocument:
    """마크다운 파일 하나를 읽는다.

    data는 파일 앞부분 최대 MAX_IMPORT_FILE_BYTES + 1바이트다(그보다 길면 용량 초과로 본다).
    확인 순서: 확장자 → 용량 → UTF-8 → 바이너리 아님 → 비어 있지 않음.
    """
    if PurePosixPath(filename).suffix.lower() not in MARKDOWN_SUFFIXES:
        raise UnreadableFileError("마크다운(.md) 파일만 올릴 수 있어요.")
    if len(data) > MAX_IMPORT_FILE_BYTES:
        raise UnreadableFileError(f"파일이 {MAX_IMPORT_FILE_BYTES // BYTES_PER_MB}MB를 넘어요.")
    try:
        text = data.decode("utf-8-sig")  # 메모장이 붙이는 BOM은 떼어 낸다
    except UnicodeDecodeError as exc:
        raise UnreadableFileError("UTF-8로 저장된 파일만 읽을 수 있어요.") from exc
    if "\x00" in text:
        # 글자 0번(NUL)은 텍스트 파일에 없고 PostgreSQL이 저장을 거절한다
        raise UnreadableFileError("마크다운 텍스트 파일이 아닌 것 같아요.")

    content = normalize_newlines(text)
    if not content.strip():
        raise UnreadableFileError("내용이 비어 있어요.")

    title = find_title(content) or PurePosixPath(filename).stem or filename
    return ImportedDocument(title=title[:NOTE_TITLE_MAX_CHARS], content=content, source=SOURCE_MARKDOWN)
