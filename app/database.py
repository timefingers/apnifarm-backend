"""
Database connection and session management using SQLAlchemy async.
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
import os
from dotenv import load_dotenv

load_dotenv()

# Build database URL from environment variables or use default for local docker
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    # Fallback to local docker defaults if not set
    # Note: asyncpg is required for async engine
    DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/apnifarm"

# Create async engine with connection pooling
engine = create_async_engine(
    DATABASE_URL,
    echo=True, # Set to False in production
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,  # Verify connections before use
)

# Session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
SessionLocal = async_session_maker


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass


async def get_db() -> AsyncSession:
    """
    Dependency that provides a database session.
    Ensures proper cleanup after request.
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Create all database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
