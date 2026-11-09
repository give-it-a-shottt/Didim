from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """모든 DB 테이블 모델이 상속하는 기본 클래스."""
