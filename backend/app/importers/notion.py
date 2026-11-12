"""노션 페이지 → 마크다운 글 (F-005, D-001 어댑터).

노션 블록 나무를 마크다운 글로 바꿔 ImportedDocument로 돌려준다. 그 뒤는 마크다운 파일과 같은 길(나누기 → 저장)이다.
노션을 부르지 않는 순수 함수다 — 블록 읽기는 app/services/notion_service.py가 하고, 자식 블록은 "children" 키에 붙여 넘긴다.

- 제목은 맨 위 `# 제목` 한 줄로 넣는다(마크다운 노트처럼 조각 제목 경로의 맨 앞이 된다). 그래서 노션의
  제목 1 · 2 · 3은 한 단계씩 내려 `##` · `###` · `####`로 쓴다.
- 글로 옮길 수 없는 블록(이미지 · 파일 · 임베드 · 데이터베이스 · 하위 페이지 등)은 건너뛰고 개수를 센다(화면 안내).
- 목차 · 이동 경로처럼 내용이 없는 블록은 세지 않고 건너뛴다.
"""

from dataclasses import dataclass
from typing import Any

from app.config import NOTE_TITLE_MAX_CHARS
from app.importers.base import ImportedDocument
from app.importers.markdown import normalize_newlines

SOURCE_NOTION = "notion"
UNTITLED = "제목 없음"

_HEADING_LEVEL = {"heading_1": 2, "heading_2": 3, "heading_3": 4}
_LIST_TYPES = ("bulleted_list_item", "numbered_list_item", "to_do")
# 자식만 이어서 쓰는 틀 블록
_CONTAINER_TYPES = ("column_list", "column", "synced_block", "template")
# 내용이 없어 조용히 건너뛰는 블록
_SILENT_TYPES = ("breadcrumb", "table_of_contents", "link_to_page")
LIST_INDENT = "  "


@dataclass(frozen=True)
class NotionDocument:
    document: ImportedDocument
    skipped_blocks: int


@dataclass
class _Segment:
    text: str
    is_list_item: bool


def rich_text_plain(items: Any, *, keep_code_marks: bool = True) -> str:
    """노션 rich_text 배열 → 글자. 인라인 코드는 `백틱`으로 감싼다(코드 블록 안에서는 그대로)."""
    if not isinstance(items, list):
        return ""
    parts: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = item.get("plain_text")
        if not isinstance(text, str):
            continue
        annotations = item.get("annotations")
        is_code = isinstance(annotations, dict) and annotations.get("code") is True
        if keep_code_marks and is_code and text.strip() and "`" not in text:
            text = f"`{text}`"
        parts.append(text)
    return "".join(parts)


def page_title(page: dict[str, Any]) -> str:
    """페이지 객체에서 제목을 꺼낸다(속성 중 type이 title인 것). 없으면 '제목 없음'."""
    properties = page.get("properties")
    if isinstance(properties, dict):
        for prop in properties.values():
            if isinstance(prop, dict) and prop.get("type") == "title":
                title = rich_text_plain(prop.get("title"), keep_code_marks=False).replace("\n", " ").strip()
                if title:
                    return title[:NOTE_TITLE_MAX_CHARS]
    return UNTITLED


def _indent_lines(text: str, indent: str) -> str:
    return "\n".join(indent + line if line else line for line in text.split("\n"))


class _Renderer:
    def __init__(self) -> None:
        self.segments: list[_Segment] = []
        self.skipped = 0

    def emit(self, text: str, *, is_list_item: bool = False) -> None:
        self.segments.append(_Segment(text=text, is_list_item=is_list_item))

    def render(self, blocks: list[dict[str, Any]], indent: str = "") -> None:
        numbered = 0
        for block in blocks:
            block_type = block.get("type")
            numbered = numbered + 1 if block_type == "numbered_list_item" else 0
            self._render_one(block, block_type if isinstance(block_type, str) else "", indent, numbered)

    def _render_one(self, block: dict[str, Any], block_type: str, indent: str, numbered: int) -> None:
        data = block.get(block_type)
        data = data if isinstance(data, dict) else {}
        children = block.get("children")
        children = [child for child in children if isinstance(child, dict)] if isinstance(children, list) else []

        if block_type in _HEADING_LEVEL:
            text = rich_text_plain(data.get("rich_text")).replace("\n", " ").strip()
            if text:
                self.emit("#" * _HEADING_LEVEL[block_type] + " " + text)
            self.render(children, indent)  # 펼침 제목의 안쪽
        elif block_type == "paragraph":
            text = rich_text_plain(data.get("rich_text"))
            if text.strip():
                if text.lstrip().startswith("#"):
                    text = "\\" + text.lstrip()  # 글자 '#'로 시작하는 문단이 제목으로 읽히지 않게
                self.emit(_indent_lines(text, indent))
            self.render(children, indent)
        elif block_type in _LIST_TYPES:
            text = rich_text_plain(data.get("rich_text"))
            if block_type == "bulleted_list_item":
                marker = "- "
            elif block_type == "numbered_list_item":
                marker = f"{numbered}. "
            else:
                marker = "- [x] " if data.get("checked") is True else "- [ ] "
            body = _indent_lines(text, indent + " " * len(marker)).lstrip(" ") if "\n" in text else text
            self.emit(indent + marker + body, is_list_item=True)
            self.render(children, indent + LIST_INDENT)
        elif block_type in ("quote", "callout"):
            text = rich_text_plain(data.get("rich_text"))
            if text.strip():
                self.emit(_indent_lines("\n".join("> " + line for line in text.split("\n")), indent))
            self.render(children, indent)
        elif block_type == "code":
            code = rich_text_plain(data.get("rich_text"), keep_code_marks=False)
            language = data.get("language")
            lang = language if isinstance(language, str) and language.isascii() and " " not in language else ""
            fence = "````" if "```" in code else "```"
            self.emit(_indent_lines(f"{fence}{lang}\n{code}\n{fence}", indent))
        elif block_type == "toggle":
            text = rich_text_plain(data.get("rich_text"))
            if text.strip():
                self.emit(_indent_lines(text, indent))
            self.render(children, indent)
        elif block_type == "divider":
            self.emit(indent + "---")
        elif block_type == "equation":
            expression = data.get("expression")
            if isinstance(expression, str) and expression.strip():
                self.emit(_indent_lines(f"$$\n{expression}\n$$", indent))
        elif block_type == "table":
            self._render_table(data, children, indent)
        elif block_type in _CONTAINER_TYPES:
            self.render(children, indent)
        elif block_type in _SILENT_TYPES:
            return
        else:
            # 이미지 · 동영상 · 파일 · PDF · 소리 · 임베드 · 북마크 · 링크 미리보기 · 하위 페이지 · 데이터베이스 ·
            # 회의록 · 지원하지 않는 블록 — 글로 옮기지 않는다
            self.skipped += 1

    def _render_table(self, data: dict[str, Any], rows: list[dict[str, Any]], indent: str) -> None:
        lines: list[str] = []
        for row in rows:
            if row.get("type") != "table_row":
                continue
            row_data = row.get("table_row")
            cells = row_data.get("cells") if isinstance(row_data, dict) else None
            if not isinstance(cells, list):
                continue
            texts = [rich_text_plain(cell).replace("\n", " ").replace("|", "\\|").strip() for cell in cells]
            lines.append(indent + "| " + " | ".join(texts) + " |")
            if len(lines) == 1:
                lines.append(indent + "|" + "|".join(" --- " for _ in texts) + "|")
        if lines:
            self.emit("\n".join(lines))


def render_notion_page(title: str, blocks: list[dict[str, Any]]) -> NotionDocument:
    """제목 + 블록 나무 → 마크다운 노트. 본문이 비어도 제목 줄은 남는다(본문 검사는 나누기 단계에서)."""
    renderer = _Renderer()
    renderer.render(blocks)

    clean_title = title.replace("\n", " ").strip()[:NOTE_TITLE_MAX_CHARS] or UNTITLED
    parts = [f"# {clean_title}"]
    previous: _Segment | None = None
    body = ""
    for segment in renderer.segments:
        if previous is not None:
            body += "\n" if (previous.is_list_item and segment.is_list_item) else "\n\n"
        body += segment.text
        previous = segment
    if body:
        parts.append(body)
    content = normalize_newlines("\n\n".join(parts)) + "\n"
    return NotionDocument(
        document=ImportedDocument(title=clean_title, content=content, source=SOURCE_NOTION),
        skipped_blocks=renderer.skipped,
    )
