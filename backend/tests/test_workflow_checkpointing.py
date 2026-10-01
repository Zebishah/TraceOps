from types import SimpleNamespace

import ops_pilot.workflows.incident.checkpointing as checkpointing_module


def test_checkpoint_database_url_removes_sqlalchemy_driver(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        checkpointing_module,
        "get_settings",
        lambda: SimpleNamespace(
            database_url=("postgresql+psycopg://user:password@example.com/database?sslmode=require")
        ),
    )

    result = checkpointing_module.get_checkpoint_database_url()

    assert result == ("postgresql://user:password@example.com/database?sslmode=require")
