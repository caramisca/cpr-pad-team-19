-- Lab 3: several instances of the service share this database.

-- Queue entries left by a session deleted before its entries were (none are expected: the service
-- deletes the entries first). Removed so the foreign key below can be added.
DELETE FROM session_queue_entry
WHERE session_id NOT IN (SELECT id FROM sessions);

ALTER TABLE session_queue_entry
    ADD CONSTRAINT fk_session_queue_entry_session FOREIGN KEY (session_id) REFERENCES sessions (id);

-- Before this version, two instances could give two applicants the same position. Such entries are
-- renumbered 1, 2, 3, ... in the order they were presented, so the constraint below can be added.
-- Shifts without a duplicate already have exactly these positions and are left unchanged.
UPDATE session_queue_entry AS entry
SET queue_position = numbered.position
FROM (SELECT id,
             ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY queue_position, presented_at, id) AS position
      FROM session_queue_entry) AS numbered
WHERE entry.id = numbered.id
  AND entry.queue_position <> numbered.position;

-- One applicant per queue position in a shift. The service hands out positions under the session's
-- lock; this constraint makes a collision impossible even so.
ALTER TABLE session_queue_entry
    ADD CONSTRAINT uq_session_queue_entry_position UNIQUE (session_id, queue_position);

-- The unique constraint's index starts with session_id, so it also serves every lookup by session.
DROP INDEX ix_session_queue_entry_session_id;
