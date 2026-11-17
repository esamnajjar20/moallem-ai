from sqlalchemy import Column, MetaData, String, Table, create_engine

from moallem.api.app import _check_publishing_schema


def _create_schema(engine) -> None:
    metadata = MetaData()
    Table("tasks", metadata, Column("result_payload", String))
    Table("quiz_draft_snapshots", metadata, Column("id", String), Column("snapshot_hash", String))
    Table("quiz_approvals", metadata, Column("id", String), Column("idempotency_key_hash", String))
    Table("publish_intents", metadata, Column("id", String), Column("external_operation_key", String))
    Table("tool_invocations", metadata, Column("id", String), Column("external_step_key", String))
    metadata.create_all(engine)


def test_publishing_readiness_requires_every_p7_table_and_task_result_column() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        _create_schema(engine)
        _check_publishing_schema(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP TABLE tool_invocations")
        try:
            _check_publishing_schema(engine)
        except Exception as exc:
            assert "tool_invocations" in str(exc)
        else:
            raise AssertionError("readiness must reject an incomplete P7 migration")
    finally:
        engine.dispose()
