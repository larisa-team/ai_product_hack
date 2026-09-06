from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from app.config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=settings.DEBUG)

async_session = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db() -> AsyncSession:
    """Сессия на запрос. Коммит делает сам обработчик (connect.unary) ДО отдачи
    ответа — здесь только откат на исключении и закрытие. Раньше commit был после
    yield, а FastAPI выполняет exit-код yield-зависимости уже после отправки ответа."""
    async with async_session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
