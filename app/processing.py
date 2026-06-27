"""
processing.py — A regra de negócio do M2 para UMA denúncia.

Fluxo (o coração do módulo):
    denuncia.recebida  ->  classifica (modelo)  ->  define área  ->  grava no banco
                       ->  publica denuncia.classificada

A classificação (predict_proba) é CPU-bound, então roda numa thread
(`asyncio.to_thread`) para não bloquear o event loop do FastAPI/consumidor.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from pydantic import ValidationError

from . import repository
from .areas import AREA_DEFAULT
from .classifier import Classificador
from .db import SessionLocal
from .messaging import Mensageria
from .schemas import DenunciaClassificada, DenunciaRecebida

logger = logging.getLogger("m2.processing")


async def classificar_denuncia(
    texto: str, classificador: Classificador, limiar: float | None = None
) -> dict:
    """Classifica um texto numa thread e acrescenta a área responsável.

    Reaproveitado tanto pelo consumidor quanto pelo endpoint POST /classificar.
    """
    if limiar is None:
        resultado = await asyncio.to_thread(classificador.classificar, texto)
    else:
        resultado = await asyncio.to_thread(classificador.classificar, texto, 3)
        # aplica um limiar alternativo só nesta chamada
        conf = resultado["confianca"]
        resultado["revisar"] = conf < limiar
        resultado["categoria"] = None if resultado["revisar"] else resultado["top3"][0]["categoria"]
        resultado["certeza"] = Classificador._nivel_certeza(conf, resultado["revisar"])

    resultado["area_responsavel"] = resultado["categoria"] or AREA_DEFAULT
    return resultado


def montar_evento(
    denuncia: DenunciaRecebida, resultado: dict, modelo_embeddings: str
) -> DenunciaClassificada:
    """Monta o payload do evento `denuncia.classificada`."""
    categoria_modelo = resultado["categoria"]
    divergencia = (
        denuncia.assunto_usuario is not None
        and categoria_modelo is not None
        and denuncia.assunto_usuario != categoria_modelo
    )
    return DenunciaClassificada(
        id=denuncia.id,
        assunto_usuario=denuncia.assunto_usuario,
        categoria=categoria_modelo,
        divergencia=divergencia,
        area_responsavel=resultado["area_responsavel"],
        confianca=resultado["confianca"],
        certeza=resultado["certeza"],
        revisar=resultado["revisar"],
        top3=resultado["top3"],
        localizacao=denuncia.localizacao,   # repasse para o M4 (recorrência territorial)
        modelo_embeddings=modelo_embeddings,
        recebido_em=denuncia.timestamp,
        classificado_em=datetime.now(timezone.utc),
    )


def fazer_handler(classificador: Classificador, mensageria: Mensageria):
    """Cria o handler que o consumidor chama a cada mensagem `denuncia.recebida`."""

    async def handler(corpo: bytes) -> None:
        # 1) parse + validação do evento de entrada
        try:
            denuncia = DenunciaRecebida.model_validate_json(corpo)
        except ValidationError as e:
            # payload malformado: loga e deixa a exceção subir -> mensagem vai p/ DLQ
            logger.error("denuncia.recebida inválida, enviando p/ DLQ: %s", e)
            raise

        # 2) classifica
        resultado = await classificar_denuncia(denuncia.texto, classificador)
        evento = montar_evento(denuncia, resultado, classificador.modelo_embeddings)

        # 3) grava no banco (outbox: publicado=False até o broker confirmar)
        async with SessionLocal() as session:
            await repository.upsert_classificacao(
                session,
                {
                    "id": evento.id,
                    "texto": denuncia.texto,
                    "assunto_usuario": evento.assunto_usuario,
                    "categoria": evento.categoria,
                    "divergencia": evento.divergencia,
                    "area_responsavel": evento.area_responsavel,
                    "confianca": evento.confianca,
                    "certeza": evento.certeza,
                    "revisar": evento.revisar,
                    "top3": [t.model_dump() for t in evento.top3],
                    "modelo_embeddings": evento.modelo_embeddings,
                    "recebido_em": evento.recebido_em,
                    "classificado_em": evento.classificado_em,
                    "localizacao": denuncia.localizacao,
                    "publicado": False,
                },
            )

        # 4) publica denuncia.classificada (p/ M3, M4, M7)
        # Se falhar: não re-raise — a mensagem é ACKed e o registro fica com
        # publicado=False para o relay retentar. Assim erros de broker não mandam
        # denúncias válidas para a DLQ nem causam perda silenciosa.
        try:
            await mensageria.publicar(evento.model_dump(mode="json"))
            async with SessionLocal() as session:
                await repository.marcar_publicado(session, evento.id)
        except Exception as e:
            logger.error(
                "Falha ao publicar denuncia %s no broker (relay vai retentar): %s",
                evento.id, e,
            )

        cat = evento.categoria or "REVISAR"
        logger.info(
            "denuncia %s -> %s / %s (conf=%.2f%s)",
            evento.id, cat, evento.area_responsavel, evento.confianca,
            ", revisar" if evento.revisar else "",
        )

    return handler