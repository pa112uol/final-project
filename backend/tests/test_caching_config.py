import importlib

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
    def isolated_settings(self, settings, monkeypatch):
        monkeypatch.delenv("CACHE_ENABLED", raising=False)
        monkeypatch.delenv("REDIS_URL", raising=False)
        settings.REDIS_URL = REDIS_URL
        return settings

    # Django's settings module parsed this with an == "True" comparison of its
    # own, so CACHE_ENABLED=true or =1 read as False there and silently
    # disabled the whole cache regardless of what this function decided
    @pytest.mark.parametrize("value", ["True", "true", "1", "yes", "on", True])
    def test_every_spelling_of_on_enables_the_cache(
        self, isolated_settings, value
    ):
        isolated_settings.CACHE_ENABLED = value
        assert cache_enabled() is True

    @pytest.mark.parametrize("value", ["False", "false", "0", "no", False])
    def test_every_spelling_of_off_disables_the_cache(
        self, isolated_settings, value
    ):
        isolated_settings.CACHE_ENABLED = value
        assert cache_enabled() is False

    def test_defaults_to_on(self, isolated_settings):
        del isolated_settings.CACHE_ENABLED
        assert cache_enabled() is True

    # Enabled but with nowhere to connect is not usable
    def test_stays_off_without_a_redis_url(self, isolated_settings):
        isolated_settings.CACHE_ENABLED = True
        isolated_settings.REDIS_URL = ""
        assert cache_enabled() is False


# settings.CACHE_ENABLED shadows the environment for cache_enabled(), so a
# stricter parser there silently overrides every decision made above. It used to
# be an == "True" comparison, which turned CACHE_ENABLED=true into "cache off".
# Reloading is the only way to observe it, since the module reads the
# environment once at import
@pytest.mark.parametrize(
    "value,expected",
    [
        ("True", True),
        ("true", True),
        ("1", True),
        ("yes", True),
        ("False", False),
        ("false", False),
        ("0", False),
    ],
)
def test_the_settings_module_parses_every_spelling(
    monkeypatch, value, expected
):
    import backend.settings as settings_module

    monkeypatch.setenv("CACHE_ENABLED", value)
    try:
        assert importlib.reload(settings_module).CACHE_ENABLED is expected
    finally:
        monkeypatch.delenv("CACHE_ENABLED", raising=False)
        importlib.reload(settings_module)
