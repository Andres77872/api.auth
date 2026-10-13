-- Coordination row for live group graph authorization. Existing DBs also need
-- scripts/migrations/group_scope_upgrade.py --apply for bindings, indexes and FKs.
USE magic_auth;
CREATE TABLE IF NOT EXISTS group_graph_lock (
    id INT NOT NULL PRIMARY KEY,
    CONSTRAINT ck_group_graph_lock_singleton CHECK (id = 1)
) ENGINE=InnoDB;
INSERT IGNORE INTO group_graph_lock (id) VALUES (1);
