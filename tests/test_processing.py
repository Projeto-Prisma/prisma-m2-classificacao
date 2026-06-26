"""Testes da orquestração do fluxo principal (app/processing.py).

Banco e broker são mockados — nenhuma conexão real é feita.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.processing import classificar_denuncia, fazer_handler, montar_evento
from app.schemas import DenunciaRecebida


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clf_mock(categoria="Poluição", confianca=0.85, revisar=False) -> MagicMock:
    clf = MagicMock()
    clf.modelo_embeddings = "test-model"
    clf.limiar = 0.40
    clf.classificar.return_value = {
        "categoria": categoria,
        "confianca": confianca,
        "certeza": "Alta" if confianca >= 0.70 else ("Média" if not revisar else "Baixa"),
        "revisar": revisar,
        "top3": [{"categoria": categoria or "X", "confianca": confianca}],
    }
    return clf


def _session_ctx_mock():
    """Retorna um mock de async context manager que age como sessão do banco."""
    session = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return MagicMock(return_value=ctx), session


# ---------------------------------------------------------------------------
# classificar_denuncia
# ---------------------------------------------------------------------------

async def test_classificar_denuncia_adiciona_area():
    clf = _clf_mock("Crime Ambiental", 0.90)
    r = await classificar_denuncia("Queimada ilegal", clf)
    assert r["area_responsavel"] == "Meio Ambiente e Sustentabilidade"


async def test_classificar_denuncia_categoria_none_retorna_triagem():
    clf = _clf_mock(categoria=None, confianca=0.30, revisar=True)
    r = await classificar_denuncia("texto ambíguo", clf)
    assert r["area_responsavel"] == "Triagem Geral"


async def test_classificar_denuncia_limiar_override_eleva_revisar():
    """Confiança 0.45 passa pelo limiar padrão (0.40) mas falha num limiar alto."""
    clf = _clf_mock("Poluição", 0.45, revisar=False)
    r = await classificar_denuncia("texto", clf, limiar=0.60)
    assert r["revisar"] is True
    assert r["categoria"] is None
    assert r["certeza"] == "Baixa"


async def test_classificar_denuncia_limiar_override_reduz_revisar():
    """Confiança 0.45 ficaria abaixo do padrão, mas um limiar baixo a aceita."""
    clf = _clf_mock("Poluição", 0.45, revisar=True)
    r = await classificar_denuncia("texto", clf, limiar=0.30)
    assert r["revisar"] is False
    assert r["categoria"] == "Poluição"


# ---------------------------------------------------------------------------
# montar_evento
# ---------------------------------------------------------------------------

def test_montar_evento_repassa_localizacao():
    denuncia = DenunciaRecebida(
        id="d1",
        texto="Barulho",
        localizacao={"lat": -8.05, "lon": -34.9},
        timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    resultado = {
        "categoria": "Poluição Sonora",
        "area_responsavel": "Meio Ambiente e Sustentabilidade",
        "confianca": 0.80,
        "certeza": "Alta",
        "revisar": False,
        "top3": [{"categoria": "Poluição Sonora", "confianca": 0.80}],
    }
    evento = montar_evento(denuncia, resultado, "test-model")

    assert evento.id == "d1"
    assert evento.localizacao == {"lat": -8.05, "lon": -34.9}
    assert evento.recebido_em == denuncia.timestamp
    assert evento.modelo_embeddings == "test-model"


def test_montar_evento_sem_localizacao():
    denuncia = DenunciaRecebida(id="d2", texto="Lixo")
    resultado = {
        "categoria": "Coleta de Lixo",
        "area_responsavel": "Limpeza e Conservação Urbana",
        "confianca": 0.90,
        "certeza": "Alta",
        "revisar": False,
        "top3": [{"categoria": "Coleta de Lixo", "confianca": 0.90}],
    }
    evento = montar_evento(denuncia, resultado, "test-model")
    assert evento.localizacao is None


# ---------------------------------------------------------------------------
# fazer_handler
# ---------------------------------------------------------------------------

async def test_handler_fluxo_normal():
    """Mensagem válida → classifica, grava (publicado=False), publica, marca publicado."""
    clf = _clf_mock()
    mensageria = AsyncMock()
    SessionLocal_mock, session_mock = _session_ctx_mock()

    with (
        patch("app.processing.SessionLocal", SessionLocal_mock),
        patch("app.processing.repository") as mock_repo,
    ):
        mock_repo.upsert_classificacao = AsyncMock()
        mock_repo.marcar_publicado = AsyncMock()

        handler = fazer_handler(clf, mensageria)
        payload = DenunciaRecebida(id="abc", texto="Lixo na calçada")
        await handler(payload.model_dump_json().encode())

    # banco gravado, evento publicado, flag atualizado
    mock_repo.upsert_classificacao.assert_called_once()
    mensageria.publicar.assert_called_once()
    mock_repo.marcar_publicado.assert_called_once()

    # publicado=False no momento do upsert
    dados_gravados = mock_repo.upsert_classificacao.call_args[0][1]
    assert dados_gravados["publicado"] is False
    assert dados_gravados["id"] == "abc"


async def test_handler_payload_invalido_levanta_excecao():
    """JSON sem os campos obrigatórios → ValidationError sobe (mensagem vai p/ DLQ)."""
    clf = _clf_mock()
    mensageria = AsyncMock()
    handler = fazer_handler(clf, mensageria)

    with pytest.raises(ValidationError):
        await handler(b'{"campo_desconhecido": true}')

    mensageria.publicar.assert_not_called()


async def test_handler_broker_falha_nao_relanca():
    """Se o publish falhar, o handler não relança — mensagem é ACKed, outbox pendente."""
    clf = _clf_mock()
    mensageria = AsyncMock()
    mensageria.publicar.side_effect = Exception("broker down")
    SessionLocal_mock, _ = _session_ctx_mock()

    with (
        patch("app.processing.SessionLocal", SessionLocal_mock),
        patch("app.processing.repository") as mock_repo,
    ):
        mock_repo.upsert_classificacao = AsyncMock()
        mock_repo.marcar_publicado = AsyncMock()

        handler = fazer_handler(clf, mensageria)
        # não deve lançar exceção
        await handler(DenunciaRecebida(id="x", texto="Lixo").model_dump_json().encode())

    # banco foi gravado mas o marcar_publicado não chegou a rodar
    mock_repo.upsert_classificacao.assert_called_once()
    mock_repo.marcar_publicado.assert_not_called()


async def test_handler_localizacao_gravada_no_banco():
    """Localização precisa ser salva no banco para o relay poder reconstruir o evento."""
    clf = _clf_mock()
    mensageria = AsyncMock()
    SessionLocal_mock, _ = _session_ctx_mock()
    loc = {"lat": -8.05, "lon": -34.9}

    with (
        patch("app.processing.SessionLocal", SessionLocal_mock),
        patch("app.processing.repository") as mock_repo,
    ):
        mock_repo.upsert_classificacao = AsyncMock()
        mock_repo.marcar_publicado = AsyncMock()

        handler = fazer_handler(clf, mensageria)
        payload = DenunciaRecebida(id="loc1", texto="Esgoto", localizacao=loc)
        await handler(payload.model_dump_json().encode())

    dados = mock_repo.upsert_classificacao.call_args[0][1]
    assert dados["localizacao"] == loc
