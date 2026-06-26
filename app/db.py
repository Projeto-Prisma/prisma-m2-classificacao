"""
db.py — Conexão assíncrona com o PostgreSQL próprio do M2.

Usa SQLAlchemy 2.0 async + asyncpg. Expõe:
  - engine / SessionLocal (fábrica de sessões)
  - criar_tabelas(): cria o schema no startup (cômodo p/ a demo)
  - get_session(): dependência do FastAPI que entrega uma sessão por requisição
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import get_settings
from .models import Base

_settings = get_settings()

engine = create_async_engine(_settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def criar_tabelas() -> None:
    """Cria as tabelas se ainda não existirem (em produção, prefira migrações)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependência FastAPI: uma sessão por requisição, fechada ao final."""
    async with SessionLocal() as session:
        yield session