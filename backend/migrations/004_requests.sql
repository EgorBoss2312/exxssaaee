-- =====================================================================
-- ВКР: web-ИС автоматизации внутренних заявок сотрудников ООО «ЭДДА»
--      с использованием RAG-подхода (Python + PostgreSQL).
--
-- Миграция 004: подсистема жизненного цикла внутренней заявки
--               (заявки, чат-сообщения по заявке, in-app уведомления).
--
-- Логика, реализуемая прототипом (этап 1 жизненного цикла):
--   1. Сотрудник формулирует заявку в портале (текст вопроса).
--   2. Система выполняет автоматическую обработку через RAG.
--   3. Если ответ уверенный — заявка авто-закрывается со ссылками
--      на источники (resolution_kind='rag', status='closed').
--   4. Если ответ не уверенный — заявка эскалируется в подразделение
--      (rule-based классификация темы → department_target_id),
--      всем сотрудникам отдела рассылаются уведомления.
--   5. Первый сотрудник, нажавший «Взять в работу», становится
--      исполнителем (assignee_id); у остальных уведомление снимается.
--   6. В рамках заявки ведётся чат «инициатор ↔ исполнитель»;
--      по готовности исполнитель закрывает заявку.
--
-- Миграция идемпотентна (IF NOT EXISTS / ON CONFLICT DO NOTHING).
-- =====================================================================

BEGIN;

-- =====================================================================
-- 1. requests — внутренние заявки сотрудников
-- =====================================================================
CREATE TABLE IF NOT EXISTS requests (
    id                   SERIAL PRIMARY KEY,
    author_id            INTEGER      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title                VARCHAR(255) NOT NULL,
    body                 TEXT         NOT NULL,
    status               VARCHAR(32)  NOT NULL DEFAULT 'new',
    resolution_kind      VARCHAR(32),
    department_target_id INTEGER      REFERENCES departments(id) ON DELETE SET NULL,
    assignee_id          INTEGER      REFERENCES users(id) ON DELETE SET NULL,
    chat_session_id      INTEGER      REFERENCES chat_sessions(id) ON DELETE SET NULL,
    rag_query_id         INTEGER      REFERENCES rag_queries(id) ON DELETE SET NULL,
    created_at           TIMESTAMP    NOT NULL DEFAULT NOW(),
    escalated_at         TIMESTAMP,
    claimed_at           TIMESTAMP,
    closed_at            TIMESTAMP,
    closed_by_id         INTEGER      REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT ck_requests_status CHECK (
        status IN ('new','answered_by_rag','escalated','in_progress','closed')
    ),
    CONSTRAINT ck_requests_resolution CHECK (
        resolution_kind IS NULL OR resolution_kind IN ('rag','specialist')
    )
);

COMMENT ON TABLE  requests IS 'Внутренние заявки сотрудников ООО «ЭДДА» (этап 1 жизненного цикла: приём → RAG → эскалация).';
COMMENT ON COLUMN requests.status IS 'new | answered_by_rag | escalated | in_progress | closed';
COMMENT ON COLUMN requests.resolution_kind IS 'Способ закрытия: rag — автоматически по RAG; specialist — специалистом отдела.';
COMMENT ON COLUMN requests.department_target_id IS 'Отдел-получатель при эскалации; назначается rule-based классификатором.';
COMMENT ON COLUMN requests.assignee_id IS 'Сотрудник, принявший заявку в работу (claim).';

CREATE INDEX IF NOT EXISTS ix_requests_author          ON requests(author_id);
CREATE INDEX IF NOT EXISTS ix_requests_department      ON requests(department_target_id);
CREATE INDEX IF NOT EXISTS ix_requests_assignee        ON requests(assignee_id);
CREATE INDEX IF NOT EXISTS ix_requests_status          ON requests(status);
CREATE INDEX IF NOT EXISTS ix_requests_created         ON requests(created_at DESC);


-- =====================================================================
-- 2. request_messages — диалог по заявке (инициатор ↔ исполнитель)
-- =====================================================================
CREATE TABLE IF NOT EXISTS request_messages (
    id           SERIAL PRIMARY KEY,
    request_id   INTEGER   NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
    author_id    INTEGER   NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content      TEXT      NOT NULL,
    created_at   TIMESTAMP NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE request_messages IS 'Сообщения чата по заявке между инициатором и исполнителем.';

CREATE INDEX IF NOT EXISTS ix_request_messages_request ON request_messages(request_id);
CREATE INDEX IF NOT EXISTS ix_request_messages_created ON request_messages(created_at);


-- =====================================================================
-- 3. notifications — in-app уведомления (колокольчик)
-- =====================================================================
CREATE TABLE IF NOT EXISTS notifications (
    id            SERIAL PRIMARY KEY,
    recipient_id  INTEGER      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind          VARCHAR(32)  NOT NULL,
    request_id    INTEGER      REFERENCES requests(id) ON DELETE CASCADE,
    title         VARCHAR(255) NOT NULL,
    body          TEXT,
    is_read       BOOLEAN      NOT NULL DEFAULT FALSE,
    is_hidden     BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMP    NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_notifications_kind CHECK (
        kind IN ('request_escalated','request_claimed','request_message','request_closed')
    )
);

COMMENT ON TABLE  notifications IS 'In-app уведомления: эскалация заявки, новое сообщение, закрытие.';
COMMENT ON COLUMN notifications.is_hidden IS 'Снимается у остальных сотрудников отдела после claim первой заявки.';

CREATE INDEX IF NOT EXISTS ix_notifications_recipient_active
    ON notifications(recipient_id, is_read, is_hidden, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_notifications_request
    ON notifications(request_id);


COMMIT;

-- =====================================================================
-- Проверка результата (вне транзакции):
--   SELECT table_name FROM information_schema.tables
--    WHERE table_schema='public' AND table_name IN
--          ('requests','request_messages','notifications');
-- =====================================================================
