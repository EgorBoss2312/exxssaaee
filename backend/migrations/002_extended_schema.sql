-- =====================================================================
-- ВКР: web-ИС интеллектуального поиска по корпоративной базе знаний
--      ООО «ЭДДА» с использованием RAG-подхода (Python + PostgreSQL)
--
-- Миграция 002: расширение схемы БД до полной проектной модели.
--
-- Стратегия: миграция применяется ПОВЕРХ существующих 7 таблиц
-- (roles, users, documents, chunks, document_roles, chat_sessions,
-- chat_messages). Старые таблицы НЕ удаляются и НЕ переименовываются —
-- это безопасно для рабочего прототипа. Добавляются 10 новых таблиц
-- и одна nullable-колонка к users (department_id).
--
-- Запуск: Supabase Studio → SQL Editor → New query → вставить
-- содержимое файла → Run. Скрипт идемпотентен (IF NOT EXISTS).
-- =====================================================================

BEGIN;

-- =====================================================================
-- 1. departments — справочник подразделений ЭДДА
-- =====================================================================
CREATE TABLE IF NOT EXISTS departments (
    id           SERIAL PRIMARY KEY,
    code         VARCHAR(64)  NOT NULL UNIQUE,
    name         VARCHAR(255) NOT NULL,
    description  TEXT,
    parent_id    INTEGER REFERENCES departments(id) ON DELETE SET NULL,
    created_at   TIMESTAMP NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  departments IS 'Структурные подразделения ООО «ЭДДА» (производство, ОТК, ИТ-служба и т.д.).';
COMMENT ON COLUMN departments.parent_id IS 'Иерархия подразделений (отдел → группа).';

-- Связь users → departments (nullable для совместимости со старыми записями).
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS department_id INTEGER
        REFERENCES departments(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_users_department_id ON users(department_id);


-- =====================================================================
-- 2. document_categories — категории документов корпуса
-- =====================================================================
CREATE TABLE IF NOT EXISTS document_categories (
    id           SERIAL PRIMARY KEY,
    code         VARCHAR(64)  NOT NULL UNIQUE,
    name         VARCHAR(255) NOT NULL,
    description  TEXT,
    sort_order   INTEGER      NOT NULL DEFAULT 100,
    created_at   TIMESTAMP    NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE document_categories IS 'Тематические категории документов (регламенты, инструкции, кадровые и т.д.).';

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS category_id INTEGER
        REFERENCES document_categories(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_documents_category_id ON documents(category_id);


-- =====================================================================
-- 3. document_tags + 4. document_tag_links — тэги документов (M:N)
-- =====================================================================
CREATE TABLE IF NOT EXISTS document_tags (
    id          SERIAL PRIMARY KEY,
    code        VARCHAR(64)  NOT NULL UNIQUE,
    name        VARCHAR(128) NOT NULL,
    color       VARCHAR(16),
    created_at  TIMESTAMP    NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE document_tags IS 'Метки/тэги для гибкой классификации документов.';

CREATE TABLE IF NOT EXISTS document_tag_links (
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    tag_id      INTEGER NOT NULL REFERENCES document_tags(id) ON DELETE CASCADE,
    PRIMARY KEY (document_id, tag_id)
);

CREATE INDEX IF NOT EXISTS ix_document_tag_links_tag ON document_tag_links(tag_id);


-- =====================================================================
-- 5. document_versions — история редакций документа
-- =====================================================================
CREATE TABLE IF NOT EXISTS document_versions (
    id              SERIAL PRIMARY KEY,
    document_id     INTEGER      NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version_number  INTEGER      NOT NULL,
    storage_path    VARCHAR(1024) NOT NULL,
    file_size       BIGINT,
    file_hash       VARCHAR(64),
    change_note     TEXT,
    uploaded_by_id  INTEGER      REFERENCES users(id) ON DELETE SET NULL,
    created_at      TIMESTAMP    NOT NULL DEFAULT NOW(),
    UNIQUE (document_id, version_number)
);

COMMENT ON TABLE document_versions IS 'История версий документа: при загрузке нового файла предыдущий не удаляется, а сохраняется здесь.';

CREATE INDEX IF NOT EXISTS ix_document_versions_doc ON document_versions(document_id);


-- =====================================================================
-- 6. embedding_models — реестр моделей эмбеддингов
-- =====================================================================
CREATE TABLE IF NOT EXISTS embedding_models (
    id              SERIAL PRIMARY KEY,
    code            VARCHAR(128) NOT NULL UNIQUE,
    provider        VARCHAR(64)  NOT NULL,
    dimension       INTEGER      NOT NULL,
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    description     TEXT,
    created_at      TIMESTAMP    NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE embedding_models IS 'Реестр моделей эмбеддингов: при смене модели старые чанки помечаются как требующие переиндексации.';

INSERT INTO embedding_models (code, provider, dimension, is_active, description)
VALUES ('paraphrase-multilingual-MiniLM-L12-v2', 'sentence-transformers', 384, TRUE,
        'Многоязычная модель эмбеддингов, используемая в текущей реализации прототипа.')
ON CONFLICT (code) DO NOTHING;


-- =====================================================================
-- 7. rag_queries — журнал RAG-запросов
-- =====================================================================
CREATE TABLE IF NOT EXISTS rag_queries (
    id                  SERIAL PRIMARY KEY,
    user_id             INTEGER      REFERENCES users(id) ON DELETE SET NULL,
    session_id          INTEGER      REFERENCES chat_sessions(id) ON DELETE SET NULL,
    message_id          INTEGER      REFERENCES chat_messages(id) ON DELETE SET NULL,
    query_text          TEXT         NOT NULL,
    answer_text         TEXT,
    top_k               INTEGER      NOT NULL DEFAULT 5,
    used_llm            BOOLEAN      NOT NULL DEFAULT TRUE,
    llm_provider        VARCHAR(64),
    llm_model           VARCHAR(128),
    embedding_model_id  INTEGER      REFERENCES embedding_models(id) ON DELETE SET NULL,
    latency_ms          INTEGER,
    created_at          TIMESTAMP    NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE rag_queries IS 'Журнал RAG-запросов для аналитики качества и стоимости вызовов LLM.';

CREATE INDEX IF NOT EXISTS ix_rag_queries_user      ON rag_queries(user_id);
CREATE INDEX IF NOT EXISTS ix_rag_queries_session   ON rag_queries(session_id);
CREATE INDEX IF NOT EXISTS ix_rag_queries_created   ON rag_queries(created_at DESC);


-- =====================================================================
-- 8. query_sources — какие фрагменты ушли в контекст ответа
-- =====================================================================
CREATE TABLE IF NOT EXISTS query_sources (
    id              SERIAL PRIMARY KEY,
    rag_query_id    INTEGER NOT NULL REFERENCES rag_queries(id) ON DELETE CASCADE,
    chunk_id        INTEGER NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    rank            INTEGER NOT NULL,
    score           DOUBLE PRECISION,
    UNIQUE (rag_query_id, chunk_id)
);

COMMENT ON TABLE query_sources IS 'Привязка ответа к конкретным фрагментам документов (проверяемость RAG-ответа).';

CREATE INDEX IF NOT EXISTS ix_query_sources_chunk ON query_sources(chunk_id);


-- =====================================================================
-- 9. query_feedback — обратная связь пользователя по ответу
-- =====================================================================
CREATE TABLE IF NOT EXISTS query_feedback (
    id              SERIAL PRIMARY KEY,
    rag_query_id    INTEGER      NOT NULL REFERENCES rag_queries(id) ON DELETE CASCADE,
    user_id         INTEGER      REFERENCES users(id) ON DELETE SET NULL,
    is_helpful      BOOLEAN      NOT NULL,
    comment         TEXT,
    created_at      TIMESTAMP    NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE query_feedback IS 'Обратная связь пользователя: основа метрик качества RAG-ответов.';

CREATE INDEX IF NOT EXISTS ix_query_feedback_query ON query_feedback(rag_query_id);


-- =====================================================================
-- 10. system_settings — параметры RAG/LLM (key-value)
-- =====================================================================
CREATE TABLE IF NOT EXISTS system_settings (
    id           SERIAL PRIMARY KEY,
    key          VARCHAR(128) NOT NULL UNIQUE,
    value        TEXT         NOT NULL,
    value_type   VARCHAR(32)  NOT NULL DEFAULT 'string',
    description  TEXT,
    updated_by_id INTEGER     REFERENCES users(id) ON DELETE SET NULL,
    updated_at   TIMESTAMP    NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE system_settings IS 'Настройки системы (top_k, температура, prompt template, провайдер LLM по умолчанию).';

INSERT INTO system_settings (key, value, value_type, description) VALUES
    ('rag.top_k',              '5',       'integer', 'Количество фрагментов в контексте RAG-ответа.'),
    ('rag.min_score',          '0.25',    'float',   'Порог релевантности (косинус) для отбора кандидатов.'),
    ('llm.default_provider',   'gemini',  'string',  'Провайдер LLM по умолчанию (gemini/openai/ollama).'),
    ('llm.temperature',        '0.2',     'float',   'Температура генерации LLM-ответа.')
ON CONFLICT (key) DO NOTHING;


-- =====================================================================
-- 11. audit_log — журнал действий (раздел 2.4 ИБ)
-- =====================================================================
CREATE TABLE IF NOT EXISTS audit_log (
    id           BIGSERIAL PRIMARY KEY,
    actor_id     INTEGER      REFERENCES users(id) ON DELETE SET NULL,
    action       VARCHAR(64)  NOT NULL,
    object_type  VARCHAR(64),
    object_id    INTEGER,
    details      JSON,
    ip_address   VARCHAR(64),
    user_agent   VARCHAR(512),
    created_at   TIMESTAMP    NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE audit_log IS 'Журнал действий пользователей: вход, загрузка документа, изменение прав, RAG-запрос и т.д.';

CREATE INDEX IF NOT EXISTS ix_audit_log_actor    ON audit_log(actor_id);
CREATE INDEX IF NOT EXISTS ix_audit_log_action   ON audit_log(action);
CREATE INDEX IF NOT EXISTS ix_audit_log_created  ON audit_log(created_at DESC);


-- =====================================================================
-- Сидинг справочника подразделений (под структуру ООО «ЭДДА» из главы 1)
-- =====================================================================
INSERT INTO departments (code, name, description) VALUES
    ('admin',       'Административно-управленческий аппарат', 'Дирекция, финансовый блок, коммерческий директор.'),
    ('production',  'Производственный блок',                  'Цеха резки/перемотки, печать, упаковка, служба механика.'),
    ('qc',          'Отдел технического контроля (ОТК)',      'Входной, межоперационный и приёмочный контроль.'),
    ('warehouse',   'Складской и логистический комплекс',     'Хранение сырья и готовой продукции, отгрузка.'),
    ('purchase',    'Отдел снабжения и закупок',              'Работа с поставщиками сырья.'),
    ('sales',       'Отдел продаж и сопровождения клиентов',  'Работа с корпоративными клиентами.'),
    ('finance',     'Финансово-экономический отдел',          'Бухгалтерия, экономический анализ.'),
    ('hr',          'Отдел кадров и делопроизводства',        'Кадровый учёт, документооборот.'),
    ('it',          'Информационно-технический отдел',        'ИТ-служба: сопровождение ПО, администрирование, ИБ.')
ON CONFLICT (code) DO NOTHING;


-- =====================================================================
-- Сидинг базовых категорий документов
-- =====================================================================
INSERT INTO document_categories (code, name, description, sort_order) VALUES
    ('regulations',    'Регламенты и стандарты',         'Регламенты ОТК, стандарты упаковки, нормативные документы.', 10),
    ('tech_instr',     'Технологические инструкции',     'Инструкции по производственным операциям и эксплуатации оборудования.', 20),
    ('safety',         'Охрана труда и ТБ',              'Документы по охране труда, технике безопасности, противопожарной безопасности.', 30),
    ('hr_docs',        'Кадровые документы',             'Положения о подразделениях, должностные инструкции.', 40),
    ('commerce',       'Коммерческие документы',         'Шаблоны договоров, спецификации, прайс-листы.', 50),
    ('reports',        'Отчёты и спецификации',          'Отчёты по производству и логистике, номенклатурные справочники.', 60),
    ('orders',         'Приказы и распоряжения',         'Приказы, внутренние распоряжения, организационные документы.', 70)
ON CONFLICT (code) DO NOTHING;

COMMIT;

-- =====================================================================
-- Проверка результата (выполнять отдельно после COMMIT, не в транзакции):
--   SELECT table_name
--     FROM information_schema.tables
--    WHERE table_schema = 'public'
--    ORDER BY table_name;
--
-- Ожидаемый список (17 таблиц):
--   audit_log, chat_messages, chat_sessions, chunks, departments,
--   document_categories, document_roles, document_tag_links,
--   document_tags, document_versions, documents, embedding_models,
--   query_feedback, query_sources, rag_queries, roles, system_settings,
--   users
-- =====================================================================
