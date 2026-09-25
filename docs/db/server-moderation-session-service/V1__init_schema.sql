CREATE TABLE sessions (
    id UUID PRIMARY KEY,
    moderator_id UUID NOT NULL,
    status VARCHAR(255) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    closed_at TIMESTAMPTZ
);

CREATE TABLE session_junior_moderators (
    session_id UUID NOT NULL REFERENCES sessions (id),
    junior_moderator_id UUID NOT NULL
);

CREATE TABLE session_queue_entry (
    id UUID PRIMARY KEY,
    session_id UUID NOT NULL,
    applicant_id UUID NOT NULL,
    queue_position INTEGER NOT NULL,
    ruleset_version INTEGER,
    presented_at TIMESTAMPTZ NOT NULL,
    resolved_at TIMESTAMPTZ,
    action VARCHAR(255)
);

CREATE INDEX ix_session_queue_entry_session_id ON session_queue_entry (session_id);

CREATE TABLE session_summary (
    session_id UUID PRIMARY KEY REFERENCES sessions (id),
    applicants_processed INTEGER NOT NULL,
    correct_decisions INTEGER NOT NULL,
    incorrect_decisions INTEGER NOT NULL,
    score DOUBLE PRECISION NOT NULL
);

CREATE TABLE processed_events (
    event_id UUID PRIMARY KEY,
    event_type VARCHAR(255) NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL
);
