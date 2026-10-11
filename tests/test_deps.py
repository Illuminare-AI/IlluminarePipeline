import builtins
import sys

from factcheck.config import Settings
from factcheck.deps import build_deps
from factcheck.store.memory import InMemoryStore


def test_missing_db_extra_falls_back_to_memory_store(monkeypatch, caplog):
    """A deployment with POSTGRES_URL but no SQLAlchemy must still start."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("sqlalchemy") or name.endswith("store.postgres"):
            raise ImportError("No module named 'sqlalchemy'")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "factcheck.store.postgres", raising=False)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    settings = Settings(llm_backend="fake", postgres_url="postgres://u:p@h:5432/db", _env_file=None)
    deps = build_deps(settings)
    assert isinstance(deps.store, InMemoryStore)
    assert "Install the 'db' extra" in caplog.text
