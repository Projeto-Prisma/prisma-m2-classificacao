"""
messaging.py — Transporte RabbitMQ do M2 (consumidor + produtor), via aio-pika.

Topologia:
    exchange `denuncias` (topic, durável)
      ├─ fila `m2.denuncia.recebida`  (bind: denuncia.recebida)  <- M2 consome
      │     x-dead-letter-exchange -> `denuncias.dlx`
      └─ (publica com routing key `denuncia.classificada`)       -> M3, M4, M7

Pontos de projeto:
  • Competing consumers: TODAS as réplicas do M2 consomem da MESMA fila. Subindo
    `--scale m2=N`, o broker distribui as denúncias entre elas automaticamente.
  • Resiliência: conexão robusta (reconecta sozinha); mensagens persistentes; se o
    M2 cair, as denúncias ficam na fila e são processadas quando ele volta.
  • Mensagem-veneno: se o processamento estourar, a mensagem é rejeitada SEM
    reenfileirar e vai para a DLQ (`m2.denuncia.recebida.dlq`) — não some nem
    entra em loop infinito.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable

import aio_pika
from aio_pika.abc import AbstractIncomingMessage

from .config import Settings

logger = logging.getLogger("m2.messaging")

# handler que processa o corpo (bytes) de uma denúncia recebida
Handler = Callable[[bytes], Awaitable[None]]


class Mensageria:
    def __init__(self, cfg: Settings):
        self.cfg = cfg
        self._conn: aio_pika.RobustConnection | None = None
        self._canal: aio_pika.abc.AbstractRobustChannel | None = None
        self._exchange: aio_pika.abc.AbstractExchange | None = None
        self._fila: aio_pika.abc.AbstractQueue | None = None

    async def conectar(self) -> None:
        """Abre conexão/canal e declara exchange, fila principal e DLQ."""
        self._conn = await aio_pika.connect_robust(self.cfg.rabbitmq_url)
        self._canal = await self._conn.channel()
        await self._canal.set_qos(prefetch_count=self.cfg.prefetch)

        self._exchange = await self._canal.declare_exchange(
            self.cfg.exchange, aio_pika.ExchangeType.TOPIC, durable=True
        )

        # Dead-letter: exchange + fila para onde vão as mensagens que falharam.
        dlx_nome = f"{self.cfg.exchange}.dlx"
        dlq_nome = f"{self.cfg.fila_in}.dlq"
        dlx = await self._canal.declare_exchange(
            dlx_nome, aio_pika.ExchangeType.TOPIC, durable=True
        )
        dlq = await self._canal.declare_queue(dlq_nome, durable=True)
        await dlq.bind(dlx, routing_key="#")

        # Fila própria do M2 (durável), com dead-letter configurado.
        self._fila = await self._canal.declare_queue(
            self.cfg.fila_in,
            durable=True,
            arguments={"x-dead-letter-exchange": dlx_nome},
        )
        await self._fila.bind(self._exchange, routing_key=self.cfg.routing_in)
        logger.info(
            "Mensageria pronta: fila=%s <- %s | publica %s | prefetch=%d",
            self.cfg.fila_in, self.cfg.routing_in, self.cfg.routing_out, self.cfg.prefetch,
        )

    async def consumir(self, handler: Handler) -> None:
        """Começa a consumir. Para cada mensagem chama `handler(body)`.

        Sucesso -> ack. Exceção -> reject sem reenfileirar (vai para a DLQ).
        """
        assert self._fila is not None, "chame conectar() antes de consumir()"

        async def _on_message(message: AbstractIncomingMessage) -> None:
            async with message.process(requeue=False):  # ack no sucesso; reject->DLQ no erro
                await handler(message.body)

        await self._fila.consume(_on_message)

    async def publicar(self, payload: dict, routing_key: str | None = None) -> None:
        """Publica um evento (dict JSON-serializável) na exchange."""
        assert self._exchange is not None, "chame conectar() antes de publicar()"
        corpo = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        await self._exchange.publish(
            aio_pika.Message(
                body=corpo,
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key=routing_key or self.cfg.routing_out,
        )

    async def fechar(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            logger.info("Conexão com o RabbitMQ fechada.")

    @property
    def conectado(self) -> bool:
        return self._conn is not None and not self._conn.is_closed