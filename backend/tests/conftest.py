import pytest


@pytest.fixture(autouse=True)
def _isolate_recording_source(monkeypatch):
    # Django's settings module loads backend/.env.local as a side effect of
    # test collection (pytest-django), which would otherwise leak the
    # developer's local RECORDING_SOURCE override into every test.
    monkeypatch.delenv("RECORDING_SOURCE", raising=False)
