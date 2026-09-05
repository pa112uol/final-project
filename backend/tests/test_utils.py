import pytest
from recommendations.utils import get_field, set_field, env_flag


class TestGetField:
    def test_reads_an_attribute_from_an_object(self):
        class Obj:
            title = "Everlong"

        assert get_field(Obj(), "title") == "Everlong"

    def test_reads_a_key_from_a_dict(self):
        assert get_field({"title": "Everlong"}, "title") == "Everlong"

    def test_returns_the_default_when_the_field_is_absent(self):
        assert get_field({}, "title", "fallback") == "fallback"

    def test_returns_the_default_for_a_type_it_cannot_read(self):
        assert get_field(42, "title", "fallback") == "fallback"


class TestSetField:
    def test_writes_an_attribute_on_an_object(self):
        class Obj:
            title = "old"

        obj = Obj()
        set_field(obj, "title", "new")
        assert obj.title == "new"

    def test_writes_a_key_into_a_dict(self):
        target = {}
        set_field(target, "title", "new")
        assert target["title"] == "new"


class TestEnvFlag:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("1", True),
            ("true", True),
            ("TRUE", True),
            ("yes", True),
            ("  true  ", True),
            ("0", False),
            ("false", False),
            ("no", False),
            ("nonsense", False),
        ],
    )
    def test_recognises_the_shared_truthy_vocabulary(
        self, monkeypatch, raw, expected
    ):
        monkeypatch.setenv("RECS_TEST_FLAG", raw)
        assert env_flag("RECS_TEST_FLAG") is expected

    def test_an_unset_variable_falls_back_to_the_default(self, monkeypatch):
        monkeypatch.delenv("RECS_TEST_FLAG", raising=False)
        assert env_flag("RECS_TEST_FLAG") is False
        assert env_flag("RECS_TEST_FLAG", True) is True

    # A .env shipping "RECS_SEED_BALANCED=" must not silently disable a
    # feature that defaults on, so blank is treated as unconfigured
    @pytest.mark.parametrize("blank", ["", "   "])
    def test_a_blank_value_falls_back_to_the_default(self, monkeypatch, blank):
        monkeypatch.setenv("RECS_TEST_FLAG", blank)
        assert env_flag("RECS_TEST_FLAG", True) is True
        assert env_flag("RECS_TEST_FLAG", False) is False

    def test_an_explicit_false_overrides_a_true_default(self, monkeypatch):
        monkeypatch.setenv("RECS_TEST_FLAG", "false")
        assert env_flag("RECS_TEST_FLAG", True) is False
