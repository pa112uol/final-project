import pytest

from caching.config import KEY_PREFIX
from caching.keys import MAX_INLINE_KEY_LENGTH, build_key


def test_key_is_prefixed_and_namespaced():
    key = build_key("mb:artist", "Radiohead")
    assert key.startswith(f"{KEY_PREFIX}mb:artist:")


def test_same_arguments_produce_the_same_key():
    assert build_key("lf:tracktags", "Creep", "Radiohead") == build_key(
        "lf:tracktags", "Creep", "Radiohead"
    )


def test_different_arguments_produce_different_keys():
    assert build_key("lf:tracktags", "Creep", "Radiohead") != build_key(
        "lf:tracktags", "Creep", "Nirvana"
    )


def test_namespace_separates_identical_arguments():
    assert build_key("mb:artist", "x") != build_key("mb:recording", "x")


# Search terms and Last.fm artist names arrive with inconsistent casing and
# whitespace, which would otherwise scatter one artist across several entries
@pytest.mark.parametrize(
    "left,right",
    [
        ("The Beatles", "the beatles"),
        ("the beatles ", "the beatles"),
        ("  Radiohead  ", "radiohead"),
        ("MGMT", "mgmt"),
    ],
)
def test_normalisation_collapses_equivalent_values(left, right):
    assert build_key("lf:tagartists", left) == build_key("lf:tagartists", right)


# fetch_track_tags takes an optional mbid, so None is a real argument value and
# needs its own encoding, distinct from "" and from the literal "None"
def test_none_and_empty_string_are_distinct():
    assert build_key("lf:tracktags", None) != build_key("lf:tracktags", "")


@pytest.mark.parametrize(
    "parts",
    [
        (1, 2),
        ("a", 1),
        (True, False),
        (["x", "y"],),
        (None,),
    ],
)
def test_assorted_argument_types_build_a_string_key(parts):
    key = build_key("ns", *parts)
    assert isinstance(key, str)
    assert key.startswith(KEY_PREFIX)


# Without escaping, ("a:b", "c") and ("a", "b:c") would flatten to the same
# joined string and silently share a cache entry
def test_separator_in_a_value_cannot_forge_a_collision():
    assert build_key("ns", "a|b", "c") != build_key("ns", "a", "b|c")


@pytest.mark.parametrize(
    "left,right",
    [
        (("a\\", "b"), ("a|b",)),
        (("a\\", "b"), ("a\\|b",)),
        (("\\",), ("|",)),
    ],
)
def test_the_escape_character_cannot_forge_a_collision(left, right):
    assert build_key("ns", *left) != build_key("ns", *right)


def test_sequence_separator_in_a_value_cannot_forge_a_collision():
    assert build_key("ns", ["a,b", "c"]) != build_key("ns", ["a", "b,c"])


@pytest.mark.parametrize("value", ["a\\b", "a|b", "a,b", "\\|,"])
def test_escaped_values_are_still_stable_across_calls(value):
    assert build_key("ns", value) == build_key("ns", value)


def test_long_arguments_are_hashed_to_bound_key_length():
    key = build_key("ns", "x" * (MAX_INLINE_KEY_LENGTH * 3))
    assert len(key) < MAX_INLINE_KEY_LENGTH + len(KEY_PREFIX) + len("ns:")


def test_long_arguments_still_round_trip_to_the_same_key():
    long_value = "y" * (MAX_INLINE_KEY_LENGTH * 3)
    assert build_key("ns", long_value) == build_key("ns", long_value)


def test_distinct_long_arguments_stay_distinct():
    assert build_key("ns", "a" * 500) != build_key("ns", "b" * 500)


def test_empty_namespace_is_rejected():
    with pytest.raises(ValueError):
        build_key("")
