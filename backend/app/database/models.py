from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
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
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    state: Mapped[str] = mapped_column(String(50), nullable=False, default="RUN_STATE_STARTED")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Итоги прогона, форма соответствует monitoring.v1.RunStats
    stats: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    project: Mapped["Project"] = relationship("Project", back_populates="runs")
    news: Mapped[list["News"]] = relationship("News", back_populates="run", cascade="all, delete-orphan")


class News(Base):
    """Карточка события: один факт, о котором сообщили один или несколько источников.

    `project_id` денормализован намеренно: лента и фильтры строятся по проекту, а не по
    одному прогону, плюс карточка, добавленная вручную, не принадлежит никакому Run
    (`run_id` тогда NULL).

    Категория/важность/тип лежат строками с именем значения proto-enum (как `Run.state`),
    а не JSONB — тогда `WHERE category IN (...)` остаётся обычным индексируемым условием.
    """

    __tablename__ = "news"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id: Mapped[str | None] = mapped_column(String, ForeignKey("runs.id", ondelete="CASCADE"), nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[list] = mapped_column(JSONB, default=list)

    category: Mapped[str] = mapped_column(String(40), nullable=False, default="NEWS_CATEGORY_UNSPECIFIED")
    importance: Mapped[str] = mapped_column(String(40), nullable=False, default="NEWS_IMPORTANCE_UNSPECIFIED")
    doc_type: Mapped[str] = mapped_column(String(30), nullable=False, default="DOC_TYPE_UNSPECIFIED")
    # Форма monitoring.v1.NewsEntities: {"who","what","when","consequences"}
    entities: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    tags: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    # Скрыто из ленты, но не удалено — «удаление» в продукте не теряет данные.
    hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    run: Mapped["Run"] = relationship("Run", back_populates="news")


class Message(Base):
    """Сырой материал из источника (Telegram-пост или запись RSS-ленты).
    В proto не выходит — внутренняя кухня сбора.

    UNIQUE(project_id, content_hash) даёт дедупликацию между прогонами И между
    источниками: перепечатка одной новости в двух лентах схлопывается сама.

    `source_key` — обобщение поверх типов источников: имя канала для Telegram,
    URL ленты для RSS. `tg_msg_id` заполняется только для Telegram.
    """

    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("project_id", "content_hash", name="uq_messages_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    source_key: Mapped[str] = mapped_column(String(255), nullable=False)
    tg_msg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # NULL — ещё не проходило message-filter
    relevant: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class Task(Base):
    """Очередь задач воркера — источник правды в Postgres, не в Redis.

    Строку не удаляем и не блокируем `SELECT ... FOR UPDATE`: несколько воркеров могут
    выбрать одну и ту же pending-задачу в одном тике поллинга. Кто её реально исполняет —
    решает `claim()` в app/queue.py (Redis `SET NX EX`, единственное, для чего Redis
    остался в системе). `uq_tasks_compose_per_run` — частичный уникальный индекс,
    не даёт поставить вторую compose-задачу на run, даже если несколько extract-задач
    прогона завершились почти одновременно в разных транзакциях.
    """

    __tablename__ = "tasks"
    __table_args__ = (
        Index(
            "uq_tasks_compose_per_run",
            "run_id",
            unique=True,
            postgresql_where=text("kind = 'compose'"),
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # extract | compose
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending | done
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class SourceCursor(Base):
    """Курсор инкрементального чтения источника.

    Отдельная таблица, а не поле внутри Project.sources: JSONB там повторяет форму
    monitoring.v1.Source, и служебные поля в него подмешивать нельзя.

    Курсор зависит от типа источника: у Telegram есть сквозной номер сообщения
    (`last_msg_id`), у RSS его нет — там курсором служит дата публикации
    (`last_published_at`). Две nullable-колонки вместо полиморфной таблицы: типов
    источников два, усложнять схему ради этого не стоит.
    """

    __tablename__ = "source_cursors"

    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    source_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    last_msg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
