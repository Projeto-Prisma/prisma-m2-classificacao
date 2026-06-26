"""
areas.py — Mapa TEMÁTICO de categoria -> área responsável.

Por que isto existe e por que é "grosso" de propósito:
    O modelo prevê 60 categorias específicas (`assunto`). Resolver o ÓRGÃO exato
    (Emlurb, CTTU, Secretaria de Saúde...) NÃO é tarefa do M2: nos dados, uma
    categoria como "Fiscalização" se espalha por 16 órgãos diferentes — depende
    do contexto (fiscalização de farmácia -> Saúde; de trânsito -> CTTU). Quem
    resolve o destino final é o M5 (Roteamento), usando o cadastro do M9.

    O M2 só agrega as 60 categorias em ~11 ÁREAS amplas. Isso dá ao M5/M7 uma
    pista temática útil sem o M2 invadir a responsabilidade do roteamento.

Como editar:
    A chave de `_AREAS` é o nome da área; o valor é a lista de categorias do
    modelo que caem nela. Qualquer categoria não listada (ou denúncia marcada
    para revisão) cai em AREA_DEFAULT. Para conferir a cobertura, rode:
        python -m app.areas
"""
from __future__ import annotations

# Área usada quando a categoria é desconhecida ou a denúncia foi para revisão.
AREA_DEFAULT = "Triagem Geral"

# área responsável -> categorias do modelo
_AREAS: dict[str, list[str]] = {
    "Meio Ambiente e Sustentabilidade": [
        "Crime Ambiental",
        "Poluição",
        "Poluição Sonora",
        "Vigilância Ambiental",
    ],
    "Limpeza e Conservação Urbana": [
        "Coleta de Lixo",
        "Descarte Irregular de Lixo",
        "Manutenção e Limpeza Urbana",
    ],
    "Saúde": [
        "Agente de Saúde",
        "Conduta Médica",
        "Saúde Recife",
        "Unidades de Saúde",
        "Vigilância Sanitária",
    ],
    "Educação e Esporte Comunitário": [
        "Academia  Recife",   # grafia exata vinda do modelo (espaço duplo)
        "Academia da Cidade",
        "Creche",
        "Professor",
    ],
    "Proteção e Direitos Humanos": [
        "Acessibilidade",
        "Agressão",
        "Assédio",
        "Casa de Apoio",
        "Conselho Tutelar",
        "Criança e Adolescente",
        "População em Situação de Rua",
        "Violação de Direitos",
        "Violação do Direito do Idoso",
        "Violência contra a Pessoa Idosa",
        "Violência contra a Pessoa com Deficiência",
    ],
    "Fiscalização e Ordem Pública": [
        "Comercio Informal",
        "Construção Irregular",
        "Fiscalização",
        "Imóvel abandonado",
        "Invasão",
        "Vistoria",
    ],
    "Mobilidade e Trânsito": [
        "Estacionamento",
        "Linha Complementar",
        "Reboque",
        "Táxi",
    ],
    "Defesa Animal": [
        "Direitos Animais",
    ],
    "Integridade e Conduta Pública": [
        "Abuso de Autoridade",
        "Acumulação Indevida de Cargos Públicos",
        "Assédio Moral",
        "Ato lesivo contra a Administração Pública",
        "Conduta Antiética",
        "Conduta Inapropriada",
        "Corrupção",
        "Gestão",
        "Irregularidade Administrativa",
        "Irregularidade administrativa",
        "Irregularidades Administrativas",
        "Pagamento",
        "Prevaricação",
        "Processo",
        "Servidor",
        "Sonegação",
    ],
    "Defesa do Consumidor": [
        "Proteção e Defesa do Consumidor",
    ],
    "Encaminhamento Externo": [
        "Compesa",
        "Ministério do Trabalho e Emprego",
        "SDS",
        "SES",
    ],
}

# índice invertido: categoria -> área (montado uma vez no import)
_CATEGORIA_PARA_AREA: dict[str, str] = {
    cat: area for area, cats in _AREAS.items() for cat in cats
}


def area_responsavel(categoria: str | None) -> str:
    """Retorna a área temática da categoria, ou AREA_DEFAULT se desconhecida/nula."""
    if not categoria:
        return AREA_DEFAULT
    return _CATEGORIA_PARA_AREA.get(categoria, AREA_DEFAULT)


def areas_disponiveis() -> list[str]:
    """Lista de áreas (inclui a área default de triagem)."""
    return list(_AREAS.keys()) + [AREA_DEFAULT]


if __name__ == "__main__":
    # Confere a cobertura do mapa contra as classes reais do modelo treinado.
    import embedding_transformer  # noqa: F401  (top-level; o joblib precisa dele)
    import joblib

    art = joblib.load("modelo_denuncias.joblib")
    classes = list(art["pipeline"].classes_)
    sem_area = [c for c in classes if c not in _CATEGORIA_PARA_AREA]
    print(f"Classes do modelo: {len(classes)} | áreas: {len(_AREAS)}")
    print(f"Categorias mapeadas: {len(_CATEGORIA_PARA_AREA)}")
    if sem_area:
        print(f"\n[ATENÇÃO] {len(sem_area)} categoria(s) cairão em '{AREA_DEFAULT}':")
        for c in sem_area:
            print("  -", repr(c))
    else:
        print("\nOK: todas as categorias do modelo têm área temática.")