"""Testes do Classificador (app/classifier.py).

O pipeline sklearn é mockado — nenhum .joblib real é lido e o modelo de
embeddings não é baixado. Testamos apenas a lógica de limiar, nível de certeza
e ordenação do top-3.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.classifier import LIMIAR_FALLBACK, Classificador


def _artefato(classes: list[str], probas: list[float], limiar: float = 0.40) -> dict:
    pipeline = MagicMock()
    pipeline.classes_ = classes
    pipeline.predict_proba.return_value = np.array([probas])
    return {
        "pipeline": pipeline,
        "limiar": limiar,
        "modelo_embeddings": "test-model",
        "tipo": "LogisticRegression",
        "metricas_holdout": {"accuracy": 0.94},
        "n_treino": 500,
    }


@patch("app.classifier.joblib.load")
class TestClassificar:
    def test_alta_confianca(self, mock_load):
        mock_load.return_value = _artefato(
            ["Poluição", "Saúde Recife", "Coleta de Lixo"],
            [0.85, 0.10, 0.05],
        )
        clf = Classificador("mock.joblib")
        r = clf.classificar("Esgoto a céu aberto")

        assert r["categoria"] == "Poluição"
        assert r["confianca"] == pytest.approx(0.85, abs=1e-4)
        assert r["certeza"] == "Alta"
        assert r["revisar"] is False

    def test_media_confianca(self, mock_load):
        mock_load.return_value = _artefato(["Poluição", "Saúde Recife"], [0.60, 0.40])
        clf = Classificador("mock.joblib")
        r = clf.classificar("possível poluição")

        assert r["certeza"] == "Média"
        assert r["revisar"] is False
        assert r["categoria"] == "Poluição"

    def test_abaixo_do_limiar(self, mock_load):
        mock_load.return_value = _artefato(
            ["Poluição", "Saúde Recife", "Coleta de Lixo"],
            [0.35, 0.33, 0.32],
        )
        clf = Classificador("mock.joblib")
        r = clf.classificar("texto ambíguo")

        assert r["categoria"] is None
        assert r["revisar"] is True
        assert r["certeza"] == "Baixa"

    def test_top3_ordenado_por_probabilidade(self, mock_load):
        mock_load.return_value = _artefato(["A", "B", "C"], [0.10, 0.80, 0.10])
        clf = Classificador("mock.joblib")
        r = clf.classificar("qualquer texto")

        assert r["top3"][0]["categoria"] == "B"
        assert r["top3"][0]["confianca"] == pytest.approx(0.80, abs=1e-4)

    def test_top3_limitado_a_3(self, mock_load):
        mock_load.return_value = _artefato(
            ["A", "B", "C", "D", "E"],
            [0.30, 0.25, 0.20, 0.15, 0.10],
        )
        clf = Classificador("mock.joblib")
        r = clf.classificar("texto")

        assert len(r["top3"]) == 3

    def test_limiar_override_eleva_threshold(self, mock_load):
        mock_load.return_value = _artefato(["Poluição", "Saúde"], [0.55, 0.45], limiar=0.40)
        clf = Classificador("mock.joblib", limiar_override=0.70)

        assert clf.limiar == 0.70
        r = clf.classificar("texto")
        # confiança 0.55 < limiar_override 0.70 → deve revisar
        assert r["revisar"] is True
        assert r["categoria"] is None

    def test_limiar_do_artefato_quando_nao_ha_override(self, mock_load):
        mock_load.return_value = _artefato(["A"], [1.0], limiar=0.60)
        clf = Classificador("mock.joblib")
        assert clf.limiar == 0.60

    def test_limiar_fallback_quando_artefato_nao_tem(self, mock_load):
        artefato = _artefato(["A"], [1.0])
        del artefato["limiar"]
        mock_load.return_value = artefato
        clf = Classificador("mock.joblib")
        assert clf.limiar == LIMIAR_FALLBACK

    def test_metadados_carregados(self, mock_load):
        mock_load.return_value = _artefato(["A", "B"], [0.6, 0.4])
        clf = Classificador("mock.joblib")

        assert clf.modelo_embeddings == "test-model"
        assert clf.tipo == "LogisticRegression"
        assert clf.n_treino == 500
        assert len(clf.classes) == 2


@pytest.mark.parametrize("conf,revisar,esperado", [
    (0.70, False, "Alta"),
    (0.71, False, "Alta"),
    (0.69, False, "Média"),
    (0.40, False, "Média"),
    (0.39, True, "Baixa"),
    (0.01, True, "Baixa"),
])
def test_nivel_certeza(conf, revisar, esperado):
    assert Classificador._nivel_certeza(conf, revisar) == esperado
