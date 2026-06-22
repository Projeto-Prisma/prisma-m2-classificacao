"""
config.py — Configuração do M2 lida de variáveis de ambiente (ou de um .env).

Tudo que muda entre ambientes (dev, Docker, produção) entra aqui: URL do broker,
URL do banco, nomes de filas/exchange, limiar de rejeição. Nada de valores
"chumbados" espalhados pelo código.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
    
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="M2_", extra="ignore")

    # Aplicação
    app_nome: str = "M2 - Classificação (NLP)"
    log_level: str = "INFO"

    # Modelo
    # Caminho do artefato .joblib (relativo à raiz do projeto / WORKDIR do container.)
    modelo_path: str = "modelo_denuncias.joblib"
    # Sobrescreve o limiar de rejeição do artefato. None = usa o limiar salvo no .joblib
    limiar: float | None = None
    # Faz uma classificação "de aquecimento" no startup para já baixar/carregar o modelo de embeddings
    aquecer_no_startup: bool = True

    # RabbitMQ
    rabbitmq_url: str = "amqp://guest:guest@rabbitmq:5672/"
    exchange: str = "denuncias"          # exchange do tipo topic, compartilhada
    routing_in: str = "denuncia.recebida"      # evento consumido (do M1)
    routing_out: str = "denuncia.classificada" # evento publicado (p/ M3, M4, M7)
    fila_in: str = "m2.denuncia.recebida"      # fila própria do M2 (competing consumers)
    # QoS: quantas mensagens não-confirmadas o broker entrega por instância de cada
    # vez. Baixo = a carga se distribui melhor entre réplicas do M2 (--scale m2=N).
    prefetch: int = 8

    # PostgreSQL (banco PRÓPRIO do M2 — database-per-service)
    database_url: str = "postgresql+asyncpg://m2:m2@db-m2:5432/m2"
    # Cria as tabelas no startup (cômodo p/ a demo; em produção use migrações).
    criar_tabelas_no_startup: bool = True

@lru_cache
def get_settings() -> Settings:
    """Instância única das configurações (cacheada)."""
    return Settings()