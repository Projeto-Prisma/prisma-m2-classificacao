"""Testes do mapa categoria -> área responsável (app/areas.py).

Nenhuma dependência externa: puro Python, sem banco nem modelo.
"""
from __future__ import annotations

import pytest

from app.areas import AREA_DEFAULT, _AREAS, _CATEGORIA_PARA_AREA, area_responsavel, areas_disponiveis


def test_categoria_conhecida():
    assert area_responsavel("Crime Ambiental") == "Meio Ambiente e Sustentabilidade"
    assert area_responsavel("Coleta de Lixo") == "Limpeza e Conservação Urbana"
    assert area_responsavel("Corrupção") == "Integridade e Conduta Pública"


def test_categoria_none_retorna_default():
    assert area_responsavel(None) == AREA_DEFAULT


def test_categoria_vazia_retorna_default():
    assert area_responsavel("") == AREA_DEFAULT


def test_categoria_desconhecida_retorna_default():
    assert area_responsavel("categoria_que_nao_existe") == AREA_DEFAULT


def test_areas_disponiveis_inclui_default():
    assert AREA_DEFAULT in areas_disponiveis()


def test_areas_disponiveis_inclui_todas_as_areas():
    for area in _AREAS:
        assert area in areas_disponiveis()


def test_sem_categorias_duplicadas():
    """Nenhuma categoria pode estar em duas áreas diferentes."""
    todas = [cat for cats in _AREAS.values() for cat in cats]
    assert len(todas) == len(set(todas)), (
        f"Categoria(s) duplicada(s) no mapa: "
        f"{[c for c in todas if todas.count(c) > 1]}"
    )


def test_indice_invertido_cobre_todas_as_categorias():
    """O índice invertido deve ter exatamente as mesmas categorias dos _AREAS."""
    esperadas = {cat for cats in _AREAS.values() for cat in cats}
    assert set(_CATEGORIA_PARA_AREA.keys()) == esperadas


@pytest.mark.parametrize("categoria,area_esperada", [
    ("Crime Ambiental", "Meio Ambiente e Sustentabilidade"),
    ("Poluição Sonora", "Meio Ambiente e Sustentabilidade"),
    ("Coleta de Lixo", "Limpeza e Conservação Urbana"),
    ("Unidades de Saúde", "Saúde"),
    ("Agressão", "Proteção e Direitos Humanos"),
    ("Construção Irregular", "Fiscalização e Ordem Pública"),
    ("Estacionamento", "Mobilidade e Trânsito"),
    ("Direitos Animais", "Defesa Animal"),
    ("Corrupção", "Integridade e Conduta Pública"),
    ("Proteção e Defesa do Consumidor", "Defesa do Consumidor"),
    ("Compesa", "Encaminhamento Externo"),
])
def test_mapeamento_por_categoria(categoria, area_esperada):
    assert area_responsavel(categoria) == area_esperada
