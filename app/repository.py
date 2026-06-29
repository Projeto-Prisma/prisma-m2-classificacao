"""
repository.py — Toda a conversa com o banco do M2 fica aqui.

O resto do serviço (consumidor, rotas) não escreve SQL: chama estas funções. Isso
mantém o acesso a dados num só lugar e fácil de testar.
"""
from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import DenunciaClassificadaDB



async def upsert_classificacao(session: AsyncSession, dados: dict) -> None:
    """Insere a classificação; se o `id` já existir, atualiza (idempotente).

    Garante correção sob reentrega do RabbitMQ (entrega "pelo menos uma vez"):
    reprocessar a mesma denúncia não cria duplicata.
    """
    stmt = pg_insert(DenunciaClassificadaDB).values(**dados)
    atualizaveis = {
        c: stmt.excluded[c]
        for c in (
            "texto", "assunto_usuario", "categoria", "categoria_sugerida", "divergencia",
            "area_responsavel", "confianca", "certeza", "revisar",
            "top3", "modelo_embeddings", "recebido_em", "classificado_em",
            "localizacao", "aguardando_revisao",
            # "publicado" intencionalmente ausente: não resetar para False
            # se a denúncia já foi publicada com sucesso em entrega anterior.
        )
    }
    stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=atualizaveis)
    await session.execute(stmt)
    await session.commit()


async def marcar_publicado(session: AsyncSession, denuncia_id: str) -> None:
    """Marca a denúncia como publicada no broker (outbox: passo final)."""
    stmt = (
        update(DenunciaClassificadaDB)
        .where(DenunciaClassificadaDB.id == denuncia_id)
        .values(publicado=True)
    )
    await session.execute(stmt)
    await session.commit()


async def listar_nao_publicados(
    session: AsyncSession, limite: int = 100
) -> list[DenunciaClassificadaDB]:
    """Retorna registros gravados mas ainda não publicados no broker.

    Exclui denúncias aguardando revisão humana: o relay não deve publicá-las
    automaticamente — elas só saem quando um humano chamar POST /denuncias/{id}/revisar.
    """
    q = (
        select(DenunciaClassificadaDB)
        .where(DenunciaClassificadaDB.publicado.is_(False))
        .where(DenunciaClassificadaDB.aguardando_revisao.is_(False))
        .order_by(DenunciaClassificadaDB.classificado_em.asc())
        .limit(limite)
    )
    return list((await session.execute(q)).scalars().all())


async def marcar_revisado(
    session: AsyncSession, denuncia_id: str, categoria_final: str, area_final: str
) -> None:
    """Aplica decisão humana: define a categoria final e libera o gate de publicação."""
    stmt = (
        update(DenunciaClassificadaDB)
        .where(DenunciaClassificadaDB.id == denuncia_id)
        .values(
            categoria=categoria_final,
            categoria_sugerida=categoria_final,
            divergencia=False,
            revisar=False,
            aguardando_revisao=False,
            area_responsavel=area_final,
        )
    )
    await session.execute(stmt)
    await session.commit()


async def buscar_por_id(session: AsyncSession, denuncia_id: str) -> DenunciaClassificadaDB | None:
    return await session.get(DenunciaClassificadaDB, denuncia_id)


async def listar(
    session: AsyncSession,
    limite: int = 50,
    offset: int = 0,
    apenas_revisar: bool = False,
    texto: str | None = None,
) -> list[DenunciaClassificadaDB]:
    q = select(DenunciaClassificadaDB).order_by(DenunciaClassificadaDB.classificado_em.desc())
    if apenas_revisar:
        q = q.where(DenunciaClassificadaDB.revisar.is_(True))
    if texto is not None:
        q = q.where(DenunciaClassificadaDB.texto == texto)
    q = q.limit(limite).offset(offset)
    return list((await session.execute(q)).scalars().all())


async def contar_total(session: AsyncSession) -> int:
    return (await session.execute(select(func.count()).select_from(DenunciaClassificadaDB))).scalar_one()


async def contar_para_revisar(session: AsyncSession) -> int:
    q = select(func.count()).select_from(DenunciaClassificadaDB).where(
        DenunciaClassificadaDB.aguardando_revisao.is_(True)
    )
    return (await session.execute(q)).scalar_one()


async def contagem_por_categoria(session: AsyncSession) -> list[tuple[str, int]]:
    q = (
        select(DenunciaClassificadaDB.categoria, func.count())
        .group_by(DenunciaClassificadaDB.categoria)
        .order_by(func.count().desc())
    )
    return [(cat or "REVISAR", n) for cat, n in (await session.execute(q)).all()]


async def contagem_por_area(session: AsyncSession) -> list[tuple[str, int]]:
    q = (
        select(DenunciaClassificadaDB.area_responsavel, func.count())
        .group_by(DenunciaClassificadaDB.area_responsavel)
        .order_by(func.count().desc())
    )
    return [(area, n) for area, n in (await session.execute(q)).all()]