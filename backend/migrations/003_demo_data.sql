-- =====================================================================
-- Миграция 003: демонстрационные данные для расширенных таблиц.
--
-- Цель: заполнить таблицы document_tags / document_tag_links /
-- document_versions, чтобы они не выглядели пустыми на скриншотах
-- Приложений Б и В дипломной работы.
--
-- Скрипт:
--   * полностью идемпотентный (ON CONFLICT DO NOTHING),
--   * привязывается к УЖЕ загруженным в систему документам
--     (не требует знания их id заранее),
--   * не трогает таблицы roles/users/documents/chunks/chat_*.
--
-- Запуск: Supabase Studio → SQL Editor → New query → вставить → Run.
-- Можно прогонять повторно без побочных эффектов.
-- =====================================================================

BEGIN;

-- =====================================================================
-- 1. Справочник тэгов
-- =====================================================================
INSERT INTO document_tags (code, name, color) VALUES
    ('actual',    'Актуально',           '#16a34a'),
    ('critical',  'Критично',            '#dc2626'),
    ('draft',     'Черновик',            '#a16207'),
    ('archive',   'Архив',               '#475569'),
    ('verified',  'Проверено',           '#0284c7'),
    ('urgent',    'Срочно',              '#ea580c'),
    ('template',  'Шаблон',              '#7c3aed')
ON CONFLICT (code) DO NOTHING;


-- =====================================================================
-- 2. Привязка тэгов к документам.
--    Каждому из первых 12 документов (по дате загрузки) — 2 тэга:
--      «Актуально» (всем)
--      второй тэг циклически из набора (verified, critical, template,
--      draft, urgent, archive) — чтобы выборка в UI выглядела разнообразной.
-- =====================================================================
WITH ranked_docs AS (
    SELECT id,
           ROW_NUMBER() OVER (ORDER BY created_at ASC, id ASC) AS rn
      FROM documents
),
secondary_tag AS (
    SELECT id AS tag_id,
           ROW_NUMBER() OVER (ORDER BY id) AS rn
      FROM document_tags
     WHERE code IN ('verified', 'critical', 'template', 'draft', 'urgent', 'archive')
)
INSERT INTO document_tag_links (document_id, tag_id)
-- (1) тэг «Актуально» на каждый из первых 12 документов
SELECT d.id,
       (SELECT id FROM document_tags WHERE code = 'actual')
  FROM ranked_docs d
 WHERE d.rn <= 12
UNION ALL
-- (2) циклически второй тэг из набора
SELECT d.id, t.tag_id
  FROM ranked_docs d
  JOIN secondary_tag t
    ON mod((d.rn - 1), 6) + 1 = t.rn
 WHERE d.rn <= 12
ON CONFLICT (document_id, tag_id) DO NOTHING;


-- =====================================================================
-- 3. История версий: для каждого существующего документа — v1.
--    Это «первичная загрузка»: file_hash NULL (исторический документ),
--    storage_path = текущий путь, uploaded_by_id = текущий загрузивший.
-- =====================================================================
INSERT INTO document_versions (
    document_id, version_number, storage_path,
    file_size, file_hash, change_note,
    uploaded_by_id, created_at
)
SELECT
    d.id,
    1,
    d.storage_path,
    NULL,
    NULL,
    'Первичная загрузка документа',
    d.uploaded_by_id,
    d.created_at
  FROM documents d
ON CONFLICT (document_id, version_number) DO NOTHING;


-- =====================================================================
-- 4. Демонстрационная "редакция" v2 для первых 3 документов
--    (имитирует реальный сценарий «загружена обновлённая версия»).
-- =====================================================================
WITH first_three AS (
    SELECT id, storage_path, uploaded_by_id, created_at
      FROM documents
     ORDER BY created_at ASC, id ASC
     LIMIT 3
)
INSERT INTO document_versions (
    document_id, version_number, storage_path,
    file_size, file_hash, change_note,
    uploaded_by_id, created_at
)
SELECT
    id,
    2,
    storage_path,
    NULL,
    NULL,
    'Обновлена редакция документа (демо)',
    uploaded_by_id,
    NOW() - INTERVAL '2 days'
  FROM first_three
ON CONFLICT (document_id, version_number) DO NOTHING;


COMMIT;


-- =====================================================================
-- Проверка результата (отдельным запросом, после COMMIT):
--   SELECT 'document_tags' AS t, COUNT(*) FROM document_tags
--   UNION ALL SELECT 'document_tag_links', COUNT(*) FROM document_tag_links
--   UNION ALL SELECT 'document_versions',  COUNT(*) FROM document_versions;
--
-- Ожидаемые значения (зависят от количества документов в БД):
--   document_tags       = 7
--   document_tag_links  = до 24 (12 документов × 2 тэга)
--   document_versions   = N + 3, где N = число документов в системе
-- =====================================================================
