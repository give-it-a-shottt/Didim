"""어댑터가 돌려주는 공통 모양 (D-001)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ImportedDocument:
    """가져온 기록 하나. 마크다운이든 노션이든 이 모양으로 바뀐 뒤 같은 길(나누기 → 저장)을 탄다.

    content는 줄바꿈을 \\n으로 맞춘 원문이다. 조각 위치(start_offset · end_offset)는 이 문자열 기준이다.
    """

    title: str
    content: str
    source: str


class UnreadableFileError(ValueError):
    """파일을 기록으로 읽을 수 없을 때. 메시지는 화면에 그대로 보여 줄 수 있는 이유다(내부 정보 없음)."""
