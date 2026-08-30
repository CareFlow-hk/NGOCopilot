BEGIN;

SELECT pg_advisory_xact_lock(hashtext('ngopilot_schema_migrations'));

CREATE TABLE activities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    location TEXT,
    activity_code TEXT,
    source_filename TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT activities_name_bounded CHECK (char_length(btrim(name)) BETWEEN 1 AND 200),
    CONSTRAINT activities_description_bounded CHECK (description IS NULL OR char_length(description) <= 4000),
    CONSTRAINT activities_location_bounded CHECK (location IS NULL OR char_length(location) <= 300),
    CONSTRAINT activities_code_bounded CHECK (activity_code IS NULL OR char_length(activity_code) <= 100),
    CONSTRAINT activities_source_filename_bounded CHECK (source_filename IS NULL OR char_length(source_filename) <= 255),
    CONSTRAINT activities_owner_id_unique UNIQUE (user_id, id)
);

CREATE INDEX activities_by_user_name_idx ON activities (user_id, name, created_at DESC);

CREATE TABLE activity_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    activity_id UUID NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    session_date DATE NOT NULL,
    start_time TIME,
    end_time TIME,
    raw_date_text TEXT,
    CONSTRAINT activity_sessions_time_order CHECK (
        start_time IS NULL OR end_time IS NULL OR start_time < end_time
    ),
    CONSTRAINT activity_sessions_raw_date_text_bounded CHECK (
        raw_date_text IS NULL OR char_length(raw_date_text) <= 300
    )
);

CREATE INDEX activity_sessions_by_activity_idx ON activity_sessions (activity_id, session_date, start_time);
CREATE INDEX activity_sessions_by_date_idx ON activity_sessions (session_date, start_time);

CREATE TABLE members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT members_name_bounded CHECK (char_length(btrim(name)) BETWEEN 1 AND 120),
    CONSTRAINT members_owner_id_unique UNIQUE (user_id, id),
    CONSTRAINT members_owner_name_unique UNIQUE (user_id, name)
);

CREATE INDEX members_by_user_name_idx ON members (user_id, name);

CREATE TABLE member_schedule_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    member_id UUID NOT NULL,
    activity_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT member_schedule_member_owner_fk
        FOREIGN KEY (user_id, member_id) REFERENCES members(user_id, id) ON DELETE CASCADE,
    CONSTRAINT member_schedule_activity_owner_fk
        FOREIGN KEY (user_id, activity_id) REFERENCES activities(user_id, id) ON DELETE CASCADE,
    CONSTRAINT member_schedule_item_unique UNIQUE (user_id, member_id, activity_id)
);

CREATE INDEX member_schedule_by_member_idx ON member_schedule_items (user_id, member_id, created_at DESC);

INSERT INTO schema_migrations (version, name)
VALUES (3, 'activity_scheduler')
ON CONFLICT (version) DO NOTHING;

COMMIT;
