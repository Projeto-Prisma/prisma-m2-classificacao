"""
routes.py — Endpoints HTTP do M2.

O M2 é, antes de tudo, um serviço orientado a eventos (consome e publica no
RabbitMQ). A API REST aqui é de APOIO: saúde/observabilidade, classificação
avulsa para teste, e consulta da base própria (denúncias já classificadas e
estatísticas por categoria/área). O painel da gestão (M8) lê o agregado do M7,
não daqui — mas estes endpoints ajudam na demo e na depuração.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from . import repository
from .areas import area_responsavel, areas_disponiveis
from .classifier import Classificador
from .db import get_session
from .processing import classificar_denuncia
from .schemas import (
    ClassificacaoResponse,
    ClassificarRequest,
    ContagemCategoria,
    DenunciaArmazenada,
)

router = APIRouter()


def get_classificador(request: Request) -> Classificador:
    clf = getattr(request.app.state, "classificador", None)
    if clf is None:
        raise HTTPException(status_code=503, detail="Modelo ainda não carregado")
    return clf


@router.get("/health", tags=["infra"])
async def health(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    mensageria = getattr(request.app.state, "mensageria", None)
    modelo_ok = getattr(request.app.state, "classificador", None) is not None
    broker_ok = bool(mensageria and mensageria.conectado)

    db_ok = False
    try:
        await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    tudo_ok = modelo_ok and db_ok
    if not tudo_ok:
        response.status_code = 503

    return {
        "status": "ok" if tudo_ok else "degradado",
        "modelo_carregado": modelo_ok,
        "db_ok": db_ok,
        "mensageria_conectada": broker_ok,
    }


@router.get("/info", tags=["infra"])
async def info(clf: Classificador = Depends(get_classificador)):
    """Metadados do modelo e do esquema de áreas."""
    return {
        "modulo": "M2 - Classificação (NLP)",
        "tipo": clf.tipo,
        "modelo_embeddings": clf.modelo_embeddings,
        "limiar": clf.limiar,
        "n_classes": len(clf.classes),
        "n_treino": clf.n_treino,
        "metricas_holdout": clf.metricas_holdout,
        "classes": clf.classes,
        "areas": areas_disponiveis(),
    }


@router.post("/classificar", response_model=ClassificacaoResponse, tags=["classificação"])
async def classificar(req: ClassificarRequest, clf: Classificador = Depends(get_classificador)):
    """Classifica um texto na hora, sem mensageria nem persistência. Útil p/ testar."""
    resultado = await classificar_denuncia(req.texto, clf, limiar=req.limiar)
    return ClassificacaoResponse(
        categoria=resultado["categoria"],
        area_responsavel=resultado["area_responsavel"],
        confianca=resultado["confianca"],
        certeza=resultado["certeza"],
        revisar=resultado["revisar"],
        top3=resultado["top3"],
    )


@router.get("/denuncias", response_model=list[DenunciaArmazenada], tags=["consulta"])
async def listar_denuncias(
    limite: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    apenas_revisar: bool = Query(False),
    session: AsyncSession = Depends(get_session),
):
    """Lista as denúncias já classificadas (mais recentes primeiro)."""
    return await repository.listar(session, limite, offset, apenas_revisar)


@router.get("/denuncias/{denuncia_id}", response_model=DenunciaArmazenada, tags=["consulta"])
async def obter_denuncia(denuncia_id: str, session: AsyncSession = Depends(get_session)):
    den = await repository.buscar_por_id(session, denuncia_id)
    if den is None:
        raise HTTPException(status_code=404, detail="Denúncia não encontrada")
    return den


@router.get("/stats", tags=["consulta"])
async def stats(session: AsyncSession = Depends(get_session)):
    """Resumo: totais e distribuição por categoria e por área."""
    total = await repository.contar_total(session)
    revisar = await repository.contar_para_revisar(session)
    por_cat = await repository.contagem_por_categoria(session)
    por_area = await repository.contagem_por_area(session)
    return {
        "total": total,
        "para_revisar": revisar,
        "pct_revisar": round(revisar / total * 100, 1) if total else 0.0,
        "por_categoria": [ContagemCategoria(chave=c, total=n) for c, n in por_cat],
        "por_area": [ContagemCategoria(chave=a, total=n) for a, n in por_area],
    }


@router.get("/areas/{categoria}", tags=["classificação"])
async def area_da_categoria(categoria: str):
    """Mostra em qual área temática uma categoria cai (útil p/ conferir o mapa)."""
    return {"categoria": categoria, "area_responsavel": area_responsavel(categoria)}