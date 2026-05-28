-- =====================================================================
-- Миграция 003: демонстрационные данные для расширенных таблиц.
--
-- Цель: заполнить document_tags / document_tag_links,
-- чтобы они не выглядели пустыми на скриншотах Приложений Б и В.
--
-- Скрипт идемпотентный (ON CONFLICT DO NOTHING).
-- =====================================================================

BEGIN;

INSERT INTO document_tags (code, name, color) VALUES
    ('actual',    'Актуально',           '#16a34a'),
    ('critical',  'Критично',            '#dc2626'),
    ('draft',     'Черновик',            '#a16207'),
    ('archive',   'Архив',               '#475569'),
    ('verified',  'Проверено',           '#0284c7'),
    ('urgent',    'Срочно',              '#ea580c'),
    ('template',  'Шаблон',              '#7c3aed')
ON CONFLICT (code) DO NOTHING;

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
SELECT d.id,
       (SELECT id FROM document_tags WHERE code = 'actual')
  FROM ranked_docs d
 WHERE d.rn <= 12
UNION ALL
SELECT d.id, t.tag_id
  FROM ranked_docs d
  JOIN secondary_tag t
    ON mod((d.rn - 1), 6) + 1 = t.rn
 WHERE d.rn <= 12
ON CONFLICT (document_id, tag_id) DO NOTHING;

COMMIT;
