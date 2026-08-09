import pytest

from caching.config import cache_enabled, parse_bool

REDIS_URL = "redis://localhost:6379/0"


class TestParseBool:
    @pytest.mark.parametrize(
        "value", ["1", "true", "True", "TRUE", " yes ", "on", True]
    )
    def test_truthy_values(self, value):
        assert parse_bool(value) is True

    @pytest.mark.parametrize(
        "value", ["0", "false", "False", "FALSE", " no ", "off", False]
    )
    def test_falsy_values(self, value):
        assert parse_bool(value) is False

    @pytest.mark.parametrize("value", [None, "", "maybe", "  "])
    def test_unrecognised_values_take_the_default(self, value):
        assert parse_bool(value, default=True) is True
        assert parse_bool(value, default=False) is False


class TestCacheEnabled:
    @pytest.fixture(autouse=True)
    def isolated_env(self, monkeypatch):
        monkeypatch.delenv("CACHE_ENABLED", raising=False)
        monkeypatch.setenv("REDIS_URL", REDIS_URL)

    @pytest.mark.parametrize("value", ["True", "true", "1", "yes", "on"])
    def test_every_spelling_of_on_enables_the_cache(self, monkeypatch, value):
        monkeypatch.setenv("CACHE_ENABLED", value)
        assert cache_enabled() is True

    @pytest.mark.parametrize("value", ["False", "false", "0", "no"])
    def test_every_spelling_of_off_disables_the_cache(self, monkeypatch, value):
        monkeypatch.setenv("CACHE_ENABLED", value)
        assert cache_enabled() is False

    def test_defaults_to_on(self):
        assert cache_enabled() is True

    # Enabled but with nowhere to connect is not usable
    def test_stays_off_without_a_redis_url(self, monkeypatch):
        monkeypatch.setenv("CACHE_ENABLED", "True")
        monkeypatch.setenv("REDIS_URL", "")
        assert cache_enabled() is False
