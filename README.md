# M2 — Classificação (NLP)

Módulo de IA do **Tratamento Inteligente de Denúncias (Conecta Recife)**. Lê o
texto livre de cada denúncia, classifica em **categoria** (assunto) e define uma
**área responsável** temática, persiste o resultado no seu próprio banco e publica
o evento `denuncia.classificada` para os módulos seguintes.

```
M1 ──denuncia.recebida──▶  ┌──────────────────────────────┐  ── denuncia.classificada ──▶  M3, M4, M7
                           │            M2 (este)         │
                           │  classifica → área → grava   │
                           │  FastAPI + RabbitMQ + PG     │
                           └──────────────────────────────┘
```

## O modelo

Pipeline **sentence-transformers (embeddings) → LogisticRegression**, treinado por
vocês (`treinar_modelo_embeddings.py`) e salvo em `modelo_denuncias.joblib`:

- **60 categorias** (`assunto`); embeddings multilíngues `paraphrase-multilingual-MiniLM-L12-v2`
- Holdout: **acurácia 0.94 · macro-F1 0.89 · weighted-F1 0.95**
- **Limiar de rejeição 0.40**: abaixo disso a denúncia volta como `categoria=null` e
  `revisar=true` (em vez de um rótulo forçado) — pensado para uma fila de revisão humana.

A lógica de inferência é a mesma do `classificador.py` (limiar, nível de
certeza, top-3), só carregada **uma vez** no startup. Como `predict_proba` é
CPU-bound, ela roda numa thread (`asyncio.to_thread`) para não travar o event loop.

## categoria × área responsável (decisão de projeto)

O M2 publica categoria **e** área responsável. Duas observações
guiaram a implementação:

1. **O modelo prevê a `categoria`** (uma das 60). Essa é a saída de IA.
2. **O órgão exato NÃO é tarefa do M2.** Nos dados, `Coleta de Lixo` sempre vai pra
   Emlurb, mas `Fiscalização` se espalha por **16 órgãos** e `Servidor` por **20** —
   depende do contexto. Resolver o destino final é do **M5 (Roteamento)** usando o
   cadastro do **M9**.

Então o M2 deriva uma **área temática grossa** (11 áreas, em `app/areas.py`),
agrupando as 60 categorias. É uma pista útil pro M5/M7 sem o M2 invadir o
roteamento. O mapa é um dicionário fácil de editar; rode `python -m app.areas` na
raiz para conferir a cobertura contra as classes reais do modelo.

## Contratos de evento

**Consome `denuncia.recebida`** (do M1):

**Publica `denuncia.classificada`** (para M3, M4, M7):


> **Nota:** repassamos `localizacao` e `recebido_em` no evento de saída. O M4
> precisa da localização para a recorrência territorial e, com database-per-service,
> não tem como ler o banco do M1 — então o M2 carrega esse dado adiante (padrão de
> *event-carried state transfer*). É um acréscimo ao mínimo do edital.

## Propriedades da mensageria

- **Competing consumers:** todas as réplicas do M2 consomem da **mesma fila**
  (`m2.denuncia.recebida`). `docker compose up --scale m2=3` e o broker distribui a
  carga — atende ao requisito de escalar o módulo pesado nos picos.
- **Idempotência:** o `id` da denúncia é a PK no banco; gravamos via **UPSERT**.
  Reentrega do RabbitMQ (entrega "pelo menos uma vez") não duplica.
- **Resiliência:** conexão robusta (reconecta sozinha) e mensagens persistentes. Se o
  M2 cair, as denúncias ficam na fila.
- **Mensagem-veneno:** payload inválido ou erro de processamento → a mensagem é
  rejeitada sem reenfileirar e cai na **DLQ** (`m2.denuncia.recebida.dlq`), sem sumir
  nem entrar em loop.

## Banco próprio (database-per-service)

PostgreSQL exclusivo do M2, tabela `denuncias_classificadas` (id, texto, categoria,
área, confiança, certeza, revisar, top3, modelo, timestamps). O M2 guarda a própria
cópia do texto e **não** lê o banco de ninguém. Não persiste a localização (isso é do
M1/M4) — só a repassa no evento.

## Como rodar

**Isolado (com RabbitMQ + Postgres juntos):**
```bash
docker compose up --build
# 3 réplicas do M2 (competing consumers):
docker compose up --build --scale m2=3
```
- Swagger: http://localhost:8000/docs
- Painel RabbitMQ: http://localhost:15672 (guest/guest)

> A 1ª subida baixa o modelo de embeddings (~470 MB) do HuggingFace; fica em volume
> (`hf-cache`), então só acontece uma vez.

**Local (sem Docker):** suba um RabbitMQ e um Postgres, copie `.env.example` para
`.env`, ajuste as URLs e:
```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Endpoints (API de apoio)

O M2 é orientado a eventos; a API REST é para observabilidade, teste e consulta.

| Método | Rota | Para quê |
|---|---|---|
| GET | `/health` | Liveness (não toca banco/modelo) |
| GET | `/info` | Métricas do modelo, classes, limiar, áreas |
| POST | `/classificar` | Classifica um texto na hora (sem mensageria) |
| GET | `/denuncias` | Lista classificadas (`limite`, `offset`, `apenas_revisar`) |
| GET | `/denuncias/{id}` | Uma denúncia classificada |
| GET | `/stats` | Totais e distribuição por categoria/área |
| GET | `/areas/{categoria}` | Em qual área temática a categoria cai |

Exemplo:
```bash
curl -X POST localhost:8000/classificar \
  -H 'Content-Type: application/json' \
  -d '{"texto":"Estão construindo um prédio sem alvará na esquina"}'
```

## Estrutura

```
m2-classificacao/
├── modelo_denuncias.joblib        # modelo treinado (de vocês)
├── embedding_transformer.py       # na RAIZ de propósito: o joblib referencia este
│                                  #   módulo top-level p/ desserializar o pipeline
├── requirements.txt
├── Dockerfile
├── docker-compose.yml             # M2 + RabbitMQ + Postgres (dev isolado)
├── .env.example
├── test_estrutura.py              # testes sem broker/banco/download
└── app/
    ├── config.py                  # variáveis de ambiente (prefixo M2_)
    ├── classifier.py              # carrega o .joblib e classifica (limiar/top-3)
    ├── areas.py                   # categoria -> área responsável (editável)
    ├── schemas.py                 # contratos: eventos + API
    ├── models.py                  # ORM da tabela de classificações
    ├── db.py                      # engine/sessão async + criação de tabelas
    ├── repository.py              # UPSERT idempotente + consultas/estatísticas
    ├── messaging.py               # RabbitMQ: consumidor + produtor + DLQ
    ├── processing.py              # recebida → classifica → grava → publica
    ├── routes.py                  # endpoints HTTP
    └── main.py                    # app FastAPI + lifespan
```

## Ajustes comuns

- **Limiar de rejeição:** `M2_LIMIAR=0.5` no `.env` (ou deixe vazio p/ usar o do
  modelo). Limiar maior = mais denúncias pra revisão, menos rótulos errados.
- **Áreas:** edite `app/areas.py` e rode `python -m app.areas` p/ validar.
- **Retreinar:** rode o `treinar_modelo_embeddings.py` de vocês e substitua o
  `.joblib`. O M2 não precisa de mudança — ele lê o artefato no startup.

## Sobre a versão do scikit-learn

O `requirements.txt` fixa `scikit-learn==1.9.0` — a versão que **salvou** o modelo.
Versão diferente até funciona, mas dispara `InconsistentVersionWarning` ao
desserializar. Se preferir outra versão, retreine o modelo com ela.