-- Cross-device sync state. One row, always.
--
-- `doc` is nullable so the sentinel row can exist before the first push:
-- SELECT ... FOR UPDATE on a missing row locks nothing, so two concurrent
-- first writes would both insert. The row is created here (and defensively
-- by sync_store.apply) to close that.
--
-- Idempotent — safe to re-run.

CREATE TABLE IF NOT EXISTS sync_state (
  id         text        PRIMARY KEY,
  doc        jsonb,
  version    bigint      NOT NULL DEFAULT 0,
  updated_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO sync_state (id, doc, version)
VALUES ('singleton', NULL, 0)
ON CONFLICT (id) DO NOTHING;
