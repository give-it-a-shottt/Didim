"""외부 서비스 토큰 암호화 (F-005 노션 토큰).

DB가 새어 나가도 토큰을 바로 쓸 수 없게, 저장할 때 Fernet(AES-128-CBC + HMAC-SHA256)으로 암호화한다.
키는 환경변수 NOTION_TOKEN_KEY(서버에서만, 커밋 · 문서 금지). 키를 바꾸면 기존 토큰은 풀 수 없으므로
그 사용자는 노션을 다시 연결해야 한다(토큰을 못 풀면 '끊김'으로 다룸).
"""

from cryptography.fernet import Fernet, InvalidToken


class TokenKeyError(RuntimeError):
    """암호화 키가 없거나 형식이 틀렸을 때. 서버 설정 문제다."""


class TokenDecryptError(ValueError):
    """저장된 토큰을 풀 수 없을 때(키가 바뀜 · 값이 깨짐)."""


def _fernet(key: str) -> Fernet:
    if not key:
        raise TokenKeyError("NOTION_TOKEN_KEY 환경변수가 필요해요.")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise TokenKeyError("NOTION_TOKEN_KEY 형식이 틀렸어요(Fernet 키, base64 32바이트).") from exc


def encrypt_token(token: str, key: str) -> str:
    return _fernet(key).encrypt(token.encode("utf-8")).decode("ascii")


def decrypt_token(encrypted: str, key: str) -> str:
    try:
        return _fernet(key).decrypt(encrypted.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError) as exc:
        raise TokenDecryptError("저장된 토큰을 풀 수 없어요.") from exc
