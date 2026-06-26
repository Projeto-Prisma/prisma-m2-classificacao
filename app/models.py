"""
models.py — Modelo ORM (SQLAlchemy 2.0) do banco PRÓPRIO do M2.

Uma única tabela: o registro de cada denúncia classificada. A chave primária é o
`id` da denúncia (que vem do M1) — isso torna o reprocessamento idempotente: se o
mesmo `denuncia.recebida` chegar duas vezes, fazemos UPSERT em vez de duplicar.

O M2 guarda sua PRÓPRIA cópia do texto (database-per-service: não lê o banco do
M1). A localização não pertence ao domínio do M2, mas é armazenada aqui como
suporte ao outbox: se o publish no broker falhar, o relay precisa reconstruir o
evento completo (incluindo localizacao) para republicá-lo sem perda de dados.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class DenunciaClassificadaDB(Base):
    __tablename__ = "denuncias_classificadas"

    # id da denúncia, vindo do M1 (chave primária -> idempotência via UPSERT)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    texto: Mapped[str] = mapped_column(Text, nullable=False)
    assunto_usuario: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    categoria: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    divergencia: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    area_responsavel: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    confianca: Mapped[float] = mapped_column(Float, nullable=False)
    certeza: Mapped[str] = mapped_column(String(10), nullable=False)
    revisar: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    top3: Mapped[list] = mapped_column(JSON, nullable=False)

    modelo_embeddings: Mapped[str] = mapped_column(String(120), nullable=False)
    recebido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    classificado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Outbox: localizacao é guardada só para o relay conseguir reconstruir o evento
    # completo caso o publish original tenha falhado.
    localizacao: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    publicado: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", index=True
    )