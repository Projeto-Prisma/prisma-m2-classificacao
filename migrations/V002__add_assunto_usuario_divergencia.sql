-- Migração V002: adiciona assunto_usuario e divergencia à tabela de classificações.
--
-- assunto_usuario: categoria selecionada pelo cidadão no formulário (pode ser nula
--   em denúncias recebidas antes desta migração ou quando o campo não é preenchido).
--
-- divergencia: True quando o cidadão escolheu uma categoria diferente da predita
--   pelo modelo. Denúncias antigas ficam com FALSE (valor conservador: sem dado
--   suficiente para afirmar divergência).
--
-- Ambas as colunas recebem DEFAULT seguro para não quebrar linhas existentes.

ALTER TABLE denuncias_classificadas
    ADD COLUMN IF NOT EXISTS assunto_usuario VARCHAR(120) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS divergencia     BOOLEAN      NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS ix_denuncias_classificadas_assunto_usuario
    ON denuncias_classificadas (assunto_usuario);

CREATE INDEX IF NOT EXISTS ix_denuncias_classificadas_divergencia
    ON denuncias_classificadas (divergencia);
