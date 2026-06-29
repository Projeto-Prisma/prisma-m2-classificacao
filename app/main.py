"""
main.py — Monta o serviço M2 e o seu ciclo de vida.

No startup (lifespan):
    1. carrega o modelo (.joblib) e, opcionalmente, faz um "aquecimento"
       para já baixar/carregar o modelo de embeddings;
    2. cria as tabelas do banco próprio;
    3. conecta no RabbitMQ e começa a consumir `denuncia.recebida`.

No shutdown: fecha a conexão com o broker e o pool do banco.

Rodar local:  uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import repository
from .classifier import Classificador
from .config import get_settings
from .db import SessionLocal, criar_tabelas, engine
from .messaging import Mensageria
from .processing import fazer_handler
from .routes import router
from .schemas import DenunciaClassificada

cfg = get_settings()
logging.basicConfig(
    level=cfg.log_level,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
logger = logging.getLogger("m2")

_RELAY_INTERVALO = 30  # segundos entre varreduras do outbox


async def _relay_pendentes(mensageria: Mensageria) -> None:
    """Republica eventos que ficaram com publicado=False (recovery do outbox)."""
    async with SessionLocal() as session:
        pendentes = await repository.listar_nao_publicados(session)

    if not pendentes:
        return

    logger.info("Relay: %d evento(s) pendente(s) de publicação.", len(pendentes))
    for den in pendentes:
        try:
            payload = DenunciaClassificada(
                id=den.id,
                assunto_usuario=den.assunto_usuario,
                categoria=den.categoria,
                categoria_sugerida=den.categoria_sugerida,
                divergencia=den.divergencia,
                area_responsavel=den.area_responsavel,
                confianca=den.confianca,
                certeza=den.certeza,
                revisar=den.revisar,
                top3=den.top3,
                localizacao=den.localizacao,
                modelo_embeddings=den.modelo_embeddings,
                recebido_em=den.recebido_em,
                classificado_em=den.classificado_em,
            )
            await mensageria.publicar(payload.model_dump(mode="json"))
            async with SessionLocal() as session:
                await repository.marcar_publicado(session, den.id)
            logger.info("Relay: %s republicado com sucesso.", den.id)
        except Exception as e:
            logger.error("Relay: falha ao republicar %s: %s", den.id, e)


async def _loop_relay(mensageria: Mensageria) -> None:
    """Roda o relay do outbox periodicamente."""
    while True:
        if mensageria.conectado:
            try:
                await _relay_pendentes(mensageria)
            except Exception as e:
                logger.error("Relay: erro inesperado: %s", e)
        await asyncio.sleep(_RELAY_INTERVALO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1) modelo
    logger.info("Carregando modelo de %s ...", cfg.modelo_path)
    classificador = Classificador(cfg.modelo_path, limiar_override=cfg.limiar)
    app.state.classificador = classificador
    logger.info(
        "Modelo carregado: %s | %d classes | limiar=%.2f",
        classificador.modelo_embeddings, len(classificador.classes), classificador.limiar,
    )
    if cfg.aquecer_no_startup:
        try:
            logger.info("Aquecendo o modelo de embeddings (pode baixar ~470 MB na 1ª vez)...")
            classificador.aquecer()
            logger.info("Modelo de embeddings pronto.")
        except Exception as e:  # offline/sem cache: segue mesmo assim
            logger.warning("Falha ao aquecer o modelo (seguindo): %s", e)

    # 2) banco
    if cfg.criar_tabelas_no_startup:
        await criar_tabelas()
        logger.info("Tabelas verificadas/criadas no PostgreSQL.")

    # 3) mensageria + consumidor + relay do outbox
    mensageria = Mensageria(cfg)
    app.state.mensageria = mensageria
    task_relay: asyncio.Task | None = None
    await mensageria.conectar()
    await mensageria.consumir(fazer_handler(classificador, mensageria))
    task_relay = asyncio.create_task(_loop_relay(mensageria))
    logger.info("Consumindo %s — M2 no ar. Relay outbox ativo (%ds).", cfg.routing_in, _RELAY_INTERVALO)

    yield

    # shutdown
    if task_relay is not None:
        task_relay.cancel()
        try:
            await task_relay
        except asyncio.CancelledError:
            pass
    await mensageria.fechar()
    await engine.dispose()
    logger.info("M2 finalizado.")


app = FastAPI(title=cfg.app_nome, version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/", tags=["infra"])
async def raiz():
    return {"modulo": cfg.app_nome, "docs": "/docs", "health": "/health"}