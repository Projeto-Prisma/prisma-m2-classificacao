"""
embedding_transformer.py — Transformador (compatível com scikit-learn) que converte
texto em embeddings usando sentence-transformers.

O modelo de embeddings é carregado de forma preguiçosa (só quando necessário) e NÃO
é gravado no .joblib — guardamos apenas o nome dele, e ele é recarregado sob demanda.
Assim o arquivo do modelo fica leve e portátil.
"""
from sklearn.base import BaseEstimator, TransformerMixin
import numpy as np

# Modelo multilíngue leve e forte em português (~470 MB, 384 dimensões).
# Alternativas: 'sentence-transformers/distiluse-base-multilingual-cased-v2',
#               'intfloat/multilingual-e5-small'.
MODELO_PADRAO = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'


class SentenceEmbedder(BaseEstimator, TransformerMixin):
    """Converte uma lista de textos em uma matriz de embeddings."""

    def __init__(self, modelo_nome=MODELO_PADRAO, batch_size=64, normalizar=True):
        self.modelo_nome = modelo_nome
        self.batch_size = batch_size
        self.normalizar = normalizar
        self._modelo = None

    def _carregar(self):
        if self._modelo is None:
            from sentence_transformers import SentenceTransformer
            self._modelo = SentenceTransformer(self.modelo_nome)
        return self._modelo

    def fit(self, X, y=None):
        return self  # nada a aprender: o embedding é pré-treinado

    def transform(self, X):
        modelo = self._carregar()
        vetores = modelo.encode(
            [str(t) for t in X],
            batch_size=self.batch_size,
            show_progress_bar=False,
            normalize_embeddings=self.normalizar,
        )
        return np.asarray(vetores)

    # ---- não picklar o modelo pesado ----
    def __getstate__(self):
        estado = self.__dict__.copy()
        estado['_modelo'] = None
        return estado

    def __setstate__(self, estado):
        self.__dict__.update(estado)
        self._modelo = None
