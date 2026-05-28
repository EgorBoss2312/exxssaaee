-- =====================================================================
-- Миграция 005: удаление неиспользуемых в прототипе таблиц.
--
-- Убираются:
--   document_categories (+ documents.category_id)
--   document_versions
--   system_settings
--
-- Параметры RAG/LLM задаются через .env (app/config.py), не из БД.
-- Классификация документов — через document_tags.
--
-- Идемпотентно: IF EXISTS. Безопасно повторять.
-- =====================================================================

BEGIN;

ALTER TABLE documents DROP COLUMN IF EXISTS category_id;

DROP TABLE IF EXISTS document_versions CASCADE;
DROP TABLE IF EXISTS system_settings CASCADE;
DROP TABLE IF EXISTS document_categories CASCADE;

COMMIT;
