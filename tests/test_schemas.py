"""Testes dos contratos Pydantic (app/schemas.py).

Verifica que os schemas aceitam payloads válidos e rejeitam os inválidos,
sem depender de banco, broker ou modelo.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas import ClassificarRequest, DenunciaClassificada, DenunciaRecebida, Top3Item


class TestDenunciaRecebida:
    def test_payload_minimo(self):
        d = DenunciaRecebida(id="x", texto="Esgoto na rua")
        assert d.id == "x"
        assert d.localizacao is None
        assert d.foto is None
        assert d.timestamp is None

    def test_payload_completo(self):
        d = DenunciaRecebida(
            id="abc123",
            texto="Barulho excessivo",
            localizacao={"lat": -8.05, "lon": -34.9, "endereco": "Rua A, 10"},
            foto="https://example.com/foto.jpg",
            timestamp=datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc),
        )
        assert d.localizacao["lat"] == pytest.approx(-8.05)
        assert d.foto == "https://example.com/foto.jpg"

    def test_id_obrigatorio(self):
        with pytest.raises(ValidationError):
            DenunciaRecebida(texto="Esgoto")

    def test_texto_obrigatorio(self):
        with pytest.raises(ValidationError):
            DenunciaRecebida(id="x")

    def test_deserializacao_json(self):
        raw = '{"id": "d1", "texto": "Lixo na calçada"}'.encode()
        d = DenunciaRecebida.model_validate_json(raw)
        assert d.id == "d1"

    def test_json_invalido_levanta_validation_error(self):
        with pytest.raises(ValidationError):
            DenunciaRecebida.model_validate_json(b'{"invalido": true}')


class TestTop3Item:
    def test_confianca_acima_de_1_invalida(self):
        with pytest.raises(ValidationError):
            Top3Item(categoria="Poluição", confianca=1.1)

    def test_confianca_negativa_invalida(self):
        with pytest.raises(ValidationError):
            Top3Item(categoria="Poluição", confianca=-0.1)

    def test_limites_validos(self):
        assert Top3Item(categoria="A", confianca=0.0).confianca == 0.0
        assert Top3Item(categoria="A", confianca=1.0).confianca == 1.0


class TestClassificarRequest:
    def test_texto_vazio_invalido(self):
        with pytest.raises(ValidationError):
            ClassificarRequest(texto="")

    def test_limiar_fora_de_range(self):
        with pytest.raises(ValidationError):
            ClassificarRequest(texto="teste", limiar=1.5)
        with pytest.raises(ValidationError):
            ClassificarRequest(texto="teste", limiar=-0.1)

    def test_limiar_none_valido(self):
        r = ClassificarRequest(texto="teste")
        assert r.limiar is None

    def test_limiar_nos_extremos(self):
        assert ClassificarRequest(texto="t", limiar=0.0).limiar == 0.0
        assert ClassificarRequest(texto="t", limiar=1.0).limiar == 1.0


class TestDenunciaClassificada:
    def _base(self, **kwargs):
        defaults = dict(
            id="d1",
            assunto_usuario="Poluição",
            categoria="Poluição",
            categoria_sugerida="Poluição",
            divergencia=False,
            area_responsavel="Meio Ambiente e Sustentabilidade",
            confianca=0.85,
            certeza="Alta",
            revisar=False,
            top3=[{"categoria": "Poluição", "confianca": 0.85}],
            modelo_embeddings="test-model",
            classificado_em=datetime(2025, 6, 1, tzinfo=timezone.utc),
        )
        defaults.update(kwargs)
        return DenunciaClassificada(**defaults)

    def test_categoria_none_quando_revisar(self):
        d = self._base(categoria=None, revisar=True, certeza="Baixa")
        assert d.categoria is None

    def test_localizacao_opcional(self):
        d = self._base()
        assert d.localizacao is None

    def test_confianca_invalida(self):
        with pytest.raises(ValidationError):
            self._base(confianca=1.5)
