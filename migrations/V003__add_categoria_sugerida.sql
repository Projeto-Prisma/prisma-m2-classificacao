-- Migração V003: adiciona categoria_sugerida à tabela de classificações.
--
-- categoria_sugerida: top-1 predito pela IA independente do limiar de confiança.
--   Quando revisar=TRUE, o campo `categoria` é NULL (confiança insuficiente), mas
--   categoria_sugerida preserva o que a IA classificou para exibição ao operador
--   e para cálculo correto de divergência (assunto_usuario != categoria_sugerida).
--
-- Denúncias existentes recebem o valor de top3[0].categoria retroativamente via
-- UPDATE (quando possível extrair do JSON). Caso o JSON não tenha o campo, fica NULL.

ALTER TABLE denuncias_classificadas
    ADD COLUMN IF NOT EXISTS categoria_sugerida VARCHAR(120) DEFAULT NULL;

UPDATE denuncias_classificadas
SET categoria_sugerida = top3 -> 0 ->> 'categoria'
WHERE categoria_sugerida IS NULL
  AND top3 IS NOT NULL
  AND jsonb_typeof(top3::jsonb) = 'array'
  AND jsonb_array_length(top3::jsonb) > 0;

CREATE INDEX IF NOT EXISTS ix_denuncias_classificadas_categoria_sugerida
    ON denuncias_classificadas (categoria_sugerida);
