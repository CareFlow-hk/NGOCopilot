BEGIN;

SELECT pg_advisory_xact_lock(hashtext('ngopilot_schema_migrations'));

ALTER TABLE storage_objects
    ADD CONSTRAINT storage_objects_owner_id_unique UNIQUE (user_id, id);

CREATE TABLE session_storage_objects (
    user_id UUID NOT NULL,
    session_id UUID NOT NULL,
    storage_object_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, session_id, storage_object_id),
    CONSTRAINT session_storage_objects_user_fk
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT session_storage_objects_session_owner_fk
        FOREIGN KEY (user_id, session_id)
        REFERENCES chat_sessions(user_id, id) ON DELETE CASCADE,
    CONSTRAINT session_storage_objects_object_owner_fk
        FOREIGN KEY (user_id, storage_object_id)
        REFERENCES storage_objects(user_id, id) ON DELETE CASCADE
);

CREATE INDEX session_storage_objects_by_object_idx
    ON session_storage_objects (user_id, storage_object_id, session_id);

INSERT INTO session_storage_objects (user_id, session_id, storage_object_id)
SELECT storage.user_id, storage.session_id, storage.id
FROM storage_objects AS storage
WHERE storage.session_id IS NOT NULL
UNION
SELECT storage.user_id, job.session_id, storage.id
FROM storage_objects AS storage
JOIN jobs AS job
  ON job.user_id = storage.user_id
 AND job.job_id = storage.job_id
WHERE storage.job_id IS NOT NULL
  AND job.session_id IS NOT NULL
ON CONFLICT DO NOTHING;

ALTER TABLE storage_objects
    DROP CONSTRAINT storage_objects_chat_owner_fk,
    DROP CONSTRAINT storage_objects_job_owner_fk,
    DROP COLUMN session_id,
    DROP COLUMN job_id;

DROP INDEX IF EXISTS storage_objects_by_job_idx;

INSERT INTO schema_migrations (version, name)
VALUES (2, 'session_storage_links')
ON CONFLICT (version) DO NOTHING;

COMMIT;
