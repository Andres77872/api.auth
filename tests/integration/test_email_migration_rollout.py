"""RED migration/rollout tests for email activation schema.

Trace: `.dev/sdd/changes/email-activation/tasks.md` task 1.8.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_additive_email_schema_files_exist_and_define_canonical_tables():
    sql = (ROOT / "schemas/tables/09_email_activation_tables.sql").read_text()

    for table in [
        "user_emails",
        "user_email_link_tokens",
        "email_messages",
        "email_delivery_attempts",
        "email_suppressions",
        "email_idempotency_keys",
        "email_template_catalog",
        "email_templates",
    ]:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql

    assert "GENERATED ALWAYS" in sql
    assert "uk_user_emails_active_activated_email" in sql
    assert "uk_user_emails_one_primary" in sql


def test_users_email_shadow_syncs_only_from_primary_activation_change_or_removal():
    sql = (ROOT / "schemas/stored_procedures/14_email_activation.sql").read_text()

    assert "sp_consume_email_activation_token" in sql
    assert "sp_user_email_set_primary" in sql
    assert "sp_user_email_remove" in sql
    assert "UPDATE users" in sql
    assert "is_primary" in sql
    assert "email_normalized" in sql


def test_gdpr_retention_and_anonymization_routines_are_present():
    sql = (ROOT / "schemas/stored_procedures/14_email_activation.sql").read_text()

    assert "sp_email_retention_purge" in sql
    assert "sp_anonymize_user_email_data" in sql
    assert "render_payload_ciphertext = NULL" in sql
    assert "recipient_email = NULL" in sql
    assert "365" in sql
    assert "30" in sql


def test_email_template_catalog_seed_includes_all_builtin_codes():
    sql = (ROOT / "schemas/tables/09_email_activation_tables.sql").read_text()

    assert "CREATE TABLE IF NOT EXISTS email_template_catalog" in sql
    assert "allowed_variables JSON NOT NULL" in sql
    assert "required_variables JSON NOT NULL" in sql
    assert "is_enabled BOOLEAN NOT NULL DEFAULT TRUE" in sql
    assert "revision INT NOT NULL DEFAULT 1" in sql
    for code in [
        "email_activation",
        "password_reset",
        "admin_password_reset",
        "security_notification",
        "delivery_operation",
        "patreon_link_proof",
        "email_credit_grant_notification",
    ]:
        assert f"'{code}'" in sql


def test_email_template_stored_procedures_are_catalog_aware():
    sql = (ROOT / "schemas/stored_procedures/14_email_activation.sql").read_text()

    for procedure in [
        "sp_email_template_get_active",
        "sp_email_template_create_dynamic",
        "sp_email_template_save_and_activate",
        "sp_email_template_disable",
        "sp_email_template_rollback",
    ]:
        assert procedure in sql
    assert "email_template_catalog" in sql
    assert "is_enabled = FALSE" in sql
    assert "revision = revision + 1" in sql
    assert "p_purpose NOT IN ('delivery_operation','security_notification')" in sql
    assert "WHEN p_status IN ('sent','retry','dead','suppressed','cancelled')" in sql


def test_schema_sync_catches_existing_env_latest_template_delivery_rollout():
    schema_sync = (ROOT / "scripts/schema_sync.py").read_text()
    canonical_tables = (ROOT / "schemas/tables/09_email_activation_tables.sql").read_text()
    canonical_sp = (ROOT / "schemas/stored_procedures/14_email_activation.sql").read_text()

    assert "email_template_catalog" in schema_sync
    assert "email_delivery_attempts.status" in schema_sync
    assert "'cancelled'" in schema_sync
    assert "stored_procedures/14_email_activation.sql" in schema_sync
    assert "CREATE TABLE IF NOT EXISTS email_template_catalog" in canonical_tables
    assert "sp_email_template_get_active" in canonical_sp


def test_bootstrap_registers_email_table_trigger_and_sp_files():
    create_py = (ROOT / "scripts/create_database.py").read_text()
    recreate_py = (ROOT / "scripts/recreate_database.py").read_text()

    for content in (create_py, recreate_py):
        assert "schemas/tables/09_email_activation_tables.sql" in content
        assert "schemas/triggers/04_email_activation_triggers.sql" in content
        assert "schemas/stored_procedures/14_email_activation.sql" in content


def test_disabled_delivery_rollout_env_is_documented_without_dropping_tables():
    env_example = (ROOT / ".env.example").read_text()
    compose_test = (ROOT / "docker-compose.test.yml").read_text()

    assert "EMAIL_DELIVERY_ENABLED=false" in env_example
    assert "EMAIL_PROVIDER=fake" in env_example
    assert "mailpit" in compose_test.lower()
    assert "axllent/mailpit" in compose_test.lower()


def test_docker_email_worker_deployment_uses_runtime_env_contract():
    compose_test = (ROOT / "docker-compose.test.yml").read_text()
    env_test = (ROOT / ".env.test").read_text()
    effective_test_env = f"{compose_test}\n{env_test}"
    dockerfile = (ROOT / "Dockerfile").read_text()
    entrypoint = (ROOT / "scripts/docker-entrypoint.sh").read_text()

    assert "CMD [\"bash\", \"scripts/docker-entrypoint.sh\"]" in dockerfile
    assert "python -m src.workers.email_worker" in entrypoint
    assert "--worker-id" in entrypoint
    assert "uvicorn src.main:app" in entrypoint

    for env_name in (
        "DB_HOST",
        "DB_USER",
        "DB_MYSQL_PASSWORD",
        "DB_NAME",
        "REDIS_HOST",
        "EMAIL_DELIVERY_ENABLED",
        "EMAIL_PROVIDER",
        "EMAIL_ALLOW_REAL_SEND_IN_TESTS",
        "MAILPIT_SMTP_HOST",
        "MAILPIT_SMTP_PORT",
        "MAILPIT_API_BASE_URL",
    ):
        assert env_name in effective_test_env, f"test Docker deployment must define {env_name}"

    assert "EMAIL_REAL_SEND_TEST_OPT_IN" not in compose_test
    assert "MAILPIT_HTTP_BASE_URL" not in compose_test


def _email_template_seed_statements() -> list[str]:
    sql = (ROOT / "schemas/tables/09_email_activation_tables.sql").read_text()
    statements = [chunk for chunk in sql.split(";") if "INSERT INTO email_templates" in chunk]
    assert len(statements) == 2, "expected the patreon_link_proof and email_credit_grant_notification seeds"
    return statements


def test_email_template_seeds_are_insert_only_on_rerun():
    """schema_sync re-executes this file; a re-run must never rewrite operator-owned version history.

    Overwriting on duplicate key reset the version-1 body and re-activated it beside the
    version an operator had saved since, leaving two active versions of one template code.
    """
    seeded_codes = set()
    for statement in _email_template_seed_statements():
        insert, _, on_duplicate = statement.partition("ON DUPLICATE KEY UPDATE")
        assert on_duplicate, "a bare INSERT would abort schema_sync on the second apply"
        assert "INSERT IGNORE" not in insert, "IGNORE would also hide truncation and constraint errors"
        for column in ("subject_template", "html_template", "text_template", "is_active", "version", "template_code"):
            assert column not in on_duplicate, f"seed must not overwrite {column} on duplicate key"
        assert on_duplicate.split() == ["id", "=", "id"], "the duplicate-key clause must stay a no-op"

        # A fresh bootstrap still ends with the template active at version 1.
        values = insert.split("VALUES", 1)[1]
        assert "\n    1,\n" in values and "\n    TRUE,\n" in values
        seeded_codes.update(code for code in ("patreon_link_proof", "email_credit_grant_notification") if f"'{code}'" in values)
    assert seeded_codes == {"patreon_link_proof", "email_credit_grant_notification"}


class _CleanupCursor:
    """Answers schema_sync._cleanup_stale_objects from a declared state and records writes."""

    def __init__(self, *, active_template_rows: int, catalog_rows: int = 0, message_refs: int = 0):
        self.active_template_rows, self.catalog_rows, self.message_refs = active_template_rows, catalog_rows, message_refs
        self.writes: list[str] = []
        self._row = None

    def execute(self, sql, params=()):
        text = " ".join(sql.split())
        lowered = text.lower()
        if lowered.startswith(("update", "delete", "drop", "insert", "alter")):
            self.writes.append(text)
            return
        if "information_schema.tables" in lowered:
            self._row = {"count": 1}
        elif "information_schema.routines" in lowered:
            self._row = {"count": 0}
        elif "from email_templates" in lowered:
            assert "is_active = true" in lowered, "only ACTIVE stale rows are work; inert history is not"
            self._row = {"count": self.active_template_rows}
        elif "from email_template_catalog" in lowered:
            self._row = {"count": self.catalog_rows}
        elif "from email_messages" in lowered:
            self._row = {"count": self.message_refs}
        else:  # pragma: no cover - a new query must be modelled here
            raise AssertionError(f"unmodelled cleanup query: {text[:80]}")

    def fetchone(self):
        return self._row


def _load_schema_sync():
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location("schema_sync_email_under_test", ROOT / "scripts/schema_sync.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve annotations through sys.modules
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def test_schema_sync_deactivates_the_stale_template_and_never_deletes_template_history():
    schema_sync = _load_schema_sync()

    # Unreferenced by any message: the old behaviour deleted every version here.
    unreferenced = _CleanupCursor(active_template_rows=2, catalog_rows=1, message_refs=0)
    actions = schema_sync._cleanup_stale_objects(unreferenced, dry_run=False)
    assert any(action.startswith("deactivate stale template free_credit_invite") for action in actions)
    template_writes = [write for write in unreferenced.writes if "email_templates" in write]
    assert len(template_writes) == 1 and template_writes[0].startswith("UPDATE email_templates SET is_active = FALSE")
    assert "AND is_active = TRUE" in template_writes[0]
    assert not any(write.upper().startswith("DELETE FROM EMAIL_TEMPLATES") for write in unreferenced.writes)
    # The catalog row is configuration for a code nothing can send; removing it is what makes the code unreachable.
    assert any(write.startswith("DELETE FROM email_template_catalog") for write in unreferenced.writes)

    # Converged: nothing active, no catalog row -> an empty plan and no write, referenced or not.
    for message_refs in (0, 3):
        converged = _CleanupCursor(active_template_rows=0, catalog_rows=0, message_refs=message_refs)
        assert schema_sync._cleanup_stale_objects(converged, dry_run=False) == []
        assert converged.writes == []

    # A dry run reports the action and writes nothing.
    preview = _CleanupCursor(active_template_rows=1)
    assert len(schema_sync._cleanup_stale_objects(preview, dry_run=True)) == 1
    assert preview.writes == []

    source = (ROOT / "scripts/schema_sync.py").read_text()
    assert "DELETE FROM email_templates" not in source
