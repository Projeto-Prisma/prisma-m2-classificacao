"""
classifier.py — Carrega o modelo treinado (.joblib) e classifica textos.

Mesma lógica do classificador.py de vocês (limiar de rejeição, nível de certeza,
top-3), só que embrulhada numa classe carregada UMA vez no startup do serviço, em
vez de reler o modelo a cada chamada.

Importante (predict_proba é CPU-bound): o método `classificar` é síncrono e
bloqueante. Quem chama a partir do código assíncrono (FastAPI / consumidor) deve
rodá-lo numa thread, p.ex. `await asyncio.to_thread(clf.classificar, texto)`,
para não travar o event loop.
"""
from __future__ import annotations

# O artefato foi salvo referenciando o módulo top-level `embedding_transformer`
# (é onde mora a classe SentenceEmbedder). Precisa estar importável para o joblib
# conseguir desserializar o pipeline de embeddings.
import embedding_transformer  # noqa: F401

import joblib
import numpy as np

LIMIAR_FALLBACK = 0.40


class Classificador:
    """Carrega o pipeline (embeddings -> LogisticRegression) e expõe `classificar`."""

    def __init__(self, caminho: str, limiar_override: float | None = None):
        artefato = joblib.load(caminho)
        self.pipeline = artefato["pipeline"]
        self.classes = list(self.pipeline.classes_)
        self.limiar = (
            limiar_override
            if limiar_override is not None
            else artefato.get("limiar", LIMIAR_FALLBACK)
        )
        self.modelo_embeddings = artefato.get("modelo_embeddings", "desconhecido")
        self.tipo = artefato.get("tipo", "desconhecido")
        self.metricas_holdout = artefato.get("metricas_holdout", {})
        self.n_treino = artefato.get("n_treino")

    def classificar(self, texto: str, top: int = 3) -> dict:
        """Classifica um texto. Retorna dict com:

            categoria  -> str prevista, ou None se confiança < limiar (revisar)
            confianca  -> probabilidade do top-1, em [0, 1]
            certeza    -> 'Alta' | 'Média' | 'Baixa'
            revisar    -> True quando ficou abaixo do limiar
            top3       -> [{'categoria': str, 'confianca': float}, ...]
        """
        probabilidades = self.pipeline.predict_proba([str(texto)])[0]
        ordem = np.argsort(probabilidades)[::-1][:top]
        top_lista = [
            {"categoria": str(self.classes[i]), "confianca": round(float(probabilidades[i]), 4)}
            for i in ordem
        ]
        conf = float(probabilidades[ordem[0]])
        revisar = conf < self.limiar
        return {
            "categoria": None if revisar else str(self.classes[ordem[0]]),
            "confianca": round(conf, 4),
            "certeza": self._nivel_certeza(conf, revisar),
            "revisar": revisar,
            "top3": top_lista,
        }

    @staticmethod
    def _nivel_certeza(conf: float, revisar: bool) -> str:
        """Traduz a confiança numérica num nível qualitativo (igual ao de vocês)."""
        if revisar:
            return "Baixa"
        if conf >= 0.70:
            return "Alta"
        return "Média"

    def aquecer(self) -> None:
        """Força o carregamento do modelo de embeddings com uma inferência boba."""
        self.classificar("aquecimento do modelo")
    