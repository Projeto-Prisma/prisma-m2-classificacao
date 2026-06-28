"""
schemas.py — Contratos de dados (Pydantic) do M2.

Dois grupos:
  1) Eventos de mensageria — o que o M2 consome e o que publica no RabbitMQ.
  2) API HTTP — corpo das requisições e respostas dos endpoints.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ----------------------------------------------------------------------------
# Itens auxiliares
# ----------------------------------------------------------------------------
class Top3Item(BaseModel):
    categoria: str
    confianca: float = Field(ge=0, le=1, description="Probabilidade em [0,1]")


# ----------------------------------------------------------------------------
# Eventos de mensageria
# ----------------------------------------------------------------------------
class DenunciaRecebida(BaseModel):
    """Payload do evento `denuncia.recebida`, produzido pelo M1 (Ingestão)."""

    id: str
    texto: str
    assunto_usuario: str | None = None # categoria selecionada pelo cidadão no formulário
    localizacao: dict | None = None    # ex.: {"lat": -8.05, "lon": -34.9, "endereco": "..."}
    foto: str | None = None            # URL/identificador da foto, se houver
    timestamp: datetime | None = None  # quando o cidadão enviou


class DenunciaClassificada(BaseModel):
    """Payload do evento `denuncia.classificada`, publicado pelo M2.

    Consumido por M3 (Priorização), M4 (Recorrência) e M7 (Analytics).

    Além do mínimo do edital (id, categoria, área responsável, confiança), o M2
    repassa `localizacao` e `recebido_em` recebidos no evento de entrada — o M4
    precisa da localização para detectar recorrência territorial e não tem outro
    caminho para obtê-la (database-per-service: ninguém lê o banco do M1).
    """

    id: str
    assunto_usuario: str | None        # categoria escolhida pelo cidadão (repasse do evento de entrada)
    categoria: str | None              # None quando revisar=True (confiança abaixo do limiar)
    categoria_sugerida: str | None     # top-1 da IA independente do limiar; permite ver a sugestão mesmo quando revisar=True
    divergencia: bool                  # True quando assunto_usuario != categoria_sugerida
    area_responsavel: str
    confianca: float = Field(ge=0, le=1)
    certeza: str                       # 'Alta' | 'Média' | 'Baixa'
    revisar: bool
    top3: list[Top3Item]
    localizacao: dict | None = None    # repasse do evento de entrada (para o M4)
    modelo_embeddings: str
    recebido_em: datetime | None = None
    classificado_em: datetime


# ----------------------------------------------------------------------------
# API HTTP
# ----------------------------------------------------------------------------
class ClassificarRequest(BaseModel):
    """Corpo do POST /classificar (classificação avulsa, sem mensageria)."""

    texto: str = Field(min_length=1)
    limiar: float | None = Field(default=None, ge=0, le=1,
                                 description="Sobrescreve o limiar de rejeição só nesta chamada")


class ClassificacaoResponse(BaseModel):
    categoria: str | None
    categoria_sugerida: str | None  # top-1 do modelo independente do limiar
    area_responsavel: str
    confianca: float
    certeza: str
    revisar: bool
    top3: list[Top3Item]


class DenunciaArmazenada(BaseModel):
    """Representação de uma denúncia já classificada e guardada no banco do M2."""

    id: str
    texto: str
    assunto_usuario: str | None
    categoria: str | None
    categoria_sugerida: str | None
    divergencia: bool
    area_responsavel: str
    confianca: float
    certeza: str
    revisar: bool
    top3: list[Top3Item]
    modelo_embeddings: str
    recebido_em: datetime | None
    classificado_em: datetime

    model_config = {"from_attributes": True}


class ContagemCategoria(BaseModel):
    chave: str
    total: int