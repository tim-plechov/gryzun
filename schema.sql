-- ============================================================
-- База данных: система учебных заданий с автопроверкой решений
-- СУБД: PostgreSQL 14+
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto"; -- для gen_random_uuid()

-- ------------------------------------------------------------
-- 1. USERS — преподаватели / администраторы
-- ------------------------------------------------------------
CREATE TABLE users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name   TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE,
    role        TEXT NOT NULL DEFAULT 'teacher' CHECK (role IN ('teacher', 'admin')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------
-- 2. TOPICS — темы заданий (с иерархией)
-- ------------------------------------------------------------
CREATE TABLE topics (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL UNIQUE,
    parent_id   UUID REFERENCES topics(id) ON DELETE SET NULL
);
CREATE INDEX idx_topics_parent ON topics(parent_id);

-- ------------------------------------------------------------
-- 3. LEVELS — уровни сложности (справочник)
-- ------------------------------------------------------------
CREATE TABLE levels (
    id          SERIAL PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,      -- 'easy' | 'medium' | 'hard' ...
    name        TEXT NOT NULL,
    sort_order  INT  NOT NULL
);

-- ------------------------------------------------------------
-- 4. TASKS — задания
-- ------------------------------------------------------------
CREATE TABLE tasks (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title        TEXT NOT NULL,
    description  TEXT NOT NULL,              -- markdown
    topic_id     UUID NOT NULL REFERENCES topics(id),
    level_id     INT  NOT NULL REFERENCES levels(id),
    author_id    UUID NOT NULL REFERENCES users(id),
    status       TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published', 'archived')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_tasks_topic  ON tasks(topic_id);
CREATE INDEX idx_tasks_level  ON tasks(level_id);
CREATE INDEX idx_tasks_author ON tasks(author_id);
CREATE INDEX idx_tasks_search ON tasks USING GIN (to_tsvector('russian', title || ' ' || description));

-- ------------------------------------------------------------
-- 5. FILES — метаданные загруженных файлов (хранятся в S3/MinIO)
-- ------------------------------------------------------------
CREATE TABLE files (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    storage_key    TEXT NOT NULL,           -- ключ объекта в S3/MinIO
    original_name  TEXT NOT NULL,
    format         TEXT NOT NULL,           -- csv, json, txt, py, xlsx ...
    mime_type      TEXT,
    size_bytes     BIGINT NOT NULL,
    checksum       TEXT NOT NULL,           -- sha256
    metadata       JSONB NOT NULL DEFAULT '{}',  -- delimiter/encoding для csv, language/version для py и т.п.
    uploaded_by    UUID REFERENCES users(id),
    uploaded_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_files_checksum ON files(checksum);

-- ------------------------------------------------------------
-- 6. TASK_DATASETS — файлы, привязанные к заданию (пример/тесты)
-- ------------------------------------------------------------
CREATE TABLE task_datasets (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id          UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    input_file_id    UUID NOT NULL REFERENCES files(id),
    output_file_id   UUID NOT NULL REFERENCES files(id),
    dataset_type     TEXT NOT NULL CHECK (dataset_type IN ('sample', 'test')), -- sample = открытый, test = закрытый
    order_index      INT  NOT NULL DEFAULT 0,
    UNIQUE (task_id, dataset_type, order_index)
);
CREATE INDEX idx_datasets_task ON task_datasets(task_id, dataset_type);

-- ------------------------------------------------------------
-- 7. STUDENTS — студенты
-- ------------------------------------------------------------
CREATE TABLE students (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name       TEXT NOT NULL,
    email           TEXT NOT NULL UNIQUE,
    student_number  TEXT UNIQUE,
    group_name      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_students_group ON students(group_name);

-- ------------------------------------------------------------
-- 8. SUBMISSIONS — решения студентов (Python-файлы)
-- ------------------------------------------------------------
CREATE TABLE submissions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id      UUID NOT NULL REFERENCES tasks(id),
    student_id   UUID NOT NULL REFERENCES students(id),
    code_file_id UUID REFERENCES files(id),   -- .py файл с решением

    status TEXT NOT NULL DEFAULT 'submitted'
        CHECK (status IN ('submitted', 'checking', 'checked', 'needs_review', 'rejected')),
        -- rejected = flagged unsafe by the automated code-safety check, never executed

    -- автопроверка (числовой результат по закрытым тестам)
    auto_score          NUMERIC(5,2),
    auto_max_score       NUMERIC(5,2),
    auto_checked_at      TIMESTAMPTZ,

    -- фидбек от LLM для студента (рекомендации по улучшению решения)
    auto_feedback              TEXT,
    auto_feedback_model        TEXT,
    auto_feedback_generated_at TIMESTAMPTZ,

    -- ручная оценка преподавателем
    human_score    NUMERIC(5,2),
    human_feedback TEXT,
    reviewed_by    UUID REFERENCES users(id),
    reviewed_at    TIMESTAMPTZ,

    final_score    NUMERIC(5,2),
    submitted_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_submissions_task    ON submissions(task_id);
CREATE INDEX idx_submissions_student ON submissions(student_id);
CREATE INDEX idx_submissions_status  ON submissions(status);

-- ------------------------------------------------------------
-- 9. SUBMISSION_TEST_RESULTS — результат прогона решения на каждом тесте
-- ------------------------------------------------------------
CREATE TABLE submission_test_results (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    submission_id      UUID NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
    task_dataset_id    UUID NOT NULL REFERENCES task_datasets(id),
    passed             BOOLEAN NOT NULL,
    stdout             TEXT,
    stderr             TEXT,
    exit_code          INT,
    execution_time_ms  INT,
    memory_kb          INT,
    checked_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_str_submission ON submission_test_results(submission_id);
CREATE INDEX idx_str_dataset    ON submission_test_results(task_dataset_id);

-- ------------------------------------------------------------
-- Начальные данные для справочника уровней
-- ------------------------------------------------------------
INSERT INTO levels (code, name, sort_order) VALUES
    ('easy',   'Лёгкий',   1),
    ('medium', 'Средний',  2),
    ('hard',   'Сложный',  3);
