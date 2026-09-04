from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Вложенные структуры храним как JSON (гибкость + простота)
    filters: Mapped[list] = mapped_column(JSONB, default=list)
    sources: Mapped[list] = mapped_column(JSONB, default=list)

    # Связь с запусками
    runs: Mapped[list["Run"]] = relationship("Run", back_populates="project", cascade="all, delete-orphan")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"), nullable=False)
    state: Mapped[str] = mapped_column(String(50), nullable=False, default="RUN_STATE_STARTED")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Итоги прогона, форма соответствует monitoring.v1.RunStats
    stats: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    project: Mapped["Project"] = relationship("Project", back_populates="runs")
    news: Mapped[list["News"]] = relationship("News", back_populates="run", cascade="all, delete-orphan")


class News(Base):
    __tablename__ = "news"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("runs.id"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[list] = mapped_column(JSONB, default=list)

    run: Mapped["Run"] = relationship("Run", back_populates="news")


class Message(Base):
    """Сырой пост из Telegram. В proto не выходит — внутренняя кухня сбора.

    UNIQUE(project_id, content_hash) даёт дедупликацию между прогонами:
    один и тот же текст повторно не обрабатывается.
    """

    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("project_id", "content_hash", name="uq_messages_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(255), nullable=False)
    tg_msg_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # NULL — ещё не проходило message-filter
    relevant: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class SourceCursor(Base):
    """Курсор инкрементального чтения канала.

    Отдельная таблица, а не поле внутри Project.sources: JSONB там повторяет форму
    monitoring.v1.Source, и служебные поля в него подмешивать нельзя.
    """

    __tablename__ = "source_cursors"

    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    channel: Mapped[str] = mapped_column(String(255), primary_key=True)
    last_msg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
