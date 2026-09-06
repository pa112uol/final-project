import pytest
from recommendations.pipeline import run_pipeline
from recommendations.scoring import score_and_sort
from recommendations.types import Candidate
from tests.test_pipeline import TEST_SEED, make_clients

NOVELTY_LEVELS = [0.0, 0.25, 0.5, 0.75, 1.0]
MOODS = [None, "chill", "energetic"]


# The identity of a returned track plus the scores that placed it there.
# Comparing this rather than the Track objects keeps the assertion on the
# ordering decisions rather than on dataclass equality
def fingerprint(tracks: list) -> list:
    return [
        (
            t.mbid,
            t.title,
            t.artist,
            t.relevance_score,
            t.novelty_score,
            t.selection_reason,
        )
        for t in tracks
    ]


def make_candidate(mbid: str, artist: str, tag_weight_sum: int, listens: int):
    return Candidate(
        title=f"Track {mbid}",
        artist=artist,
        artist_mbid=f"artist-{artist}",
        mbid=mbid,
        duration_ms=None,
        tag_weight_sum=tag_weight_sum,
        track_tag_score=0,
        listen_count=listens,
        user_count=listens // 3,
        artist_listen_count=0,
        tags=["shoegaze", "dreampop"],
    )


# Listen counts deliberately not rank-correlated with tag_weight_sum, so the
# relevance and obscurity terms never cancel to an equal blended score
@pytest.fixture
def pool():
    return [
        make_candidate("a", "Artist A", 150, 90000),
        make_candidate("b", "Artist B", 118, 4000),
        make_candidate("c", "Artist C", 83, 26000),
        make_candidate("d", "Artist D", 57, 13000),
    ]


# Every candidate carries identical relevance and popularity, so all four tie
# on final_score at any novelty setting
@pytest.fixture
def tied_pool():
    return [
        make_candidate(mbid, f"Artist {mbid.upper()}", 100, 10000)
        for mbid in ["a", "b", "c", "d"]
    ]


# Upstream sources return their pages in the reverse of the default stub order,
# so the pipeline sees the same data arriving in a different sequence
def make_reversed_clients():
    default = make_clients()

    async def fetch_tag_artists(tag, page, limit, api_key):
        artists = await default.fetch_tag_artists(tag, page, limit, api_key)
        return list(reversed(artists))

    async def fetch_top_recordings_for_artist(mbid, name, limit, api_key):
        return list(
            reversed(
                await default.fetch_top_recordings_for_artist(
                    mbid, name, limit, api_key
                )
            )
        )

    return make_clients(
        fetch_tag_artists=fetch_tag_artists,
        fetch_top_recordings_for_artist=fetch_top_recordings_for_artist,
    )


class TestScoringDeterminism:
    @pytest.mark.parametrize("novelty", NOVELTY_LEVELS)
    def test_repeated_calls_return_the_same_order(self, pool, novelty):
        first = [c.mbid for c in score_and_sort(pool, novelty)]
        second = [c.mbid for c in score_and_sort(pool, novelty)]
        assert first == second

    @pytest.mark.parametrize("novelty", NOVELTY_LEVELS)
    def test_input_order_does_not_change_the_result(self, pool, novelty):
        forward = [c.mbid for c in score_and_sort(pool, novelty)]
        reordered = score_and_sort(list(reversed(pool)), novelty)
        backward = [c.mbid for c in reordered]
        assert forward == backward

    @pytest.mark.parametrize("novelty", NOVELTY_LEVELS)
    def test_scores_separate_every_candidate(self, pool, novelty):
        scores = [c.final_score for c in score_and_sort(pool, novelty)]
        assert len(set(scores)) == len(scores)

    # score_and_sort sorts on final_score alone, so tied candidates keep the
    # order they arrived in. The pipeline supplies that order canonically
    @pytest.mark.parametrize("novelty", NOVELTY_LEVELS)
    def test_tied_scores_keep_their_input_order(self, tied_pool, novelty):
        assert [c.mbid for c in score_and_sort(tied_pool, novelty)] == [
            c.mbid for c in tied_pool
        ]

    @pytest.mark.parametrize("novelty", NOVELTY_LEVELS)
    def test_tied_scores_follow_a_reordered_input(self, tied_pool, novelty):
        reordered = list(reversed(tied_pool))
        assert [c.mbid for c in score_and_sort(reordered, novelty)] == [
            c.mbid for c in reordered
        ]


class TestPipelineDeterminism:
    @pytest.mark.parametrize("novelty", NOVELTY_LEVELS)
    async def test_the_same_request_returns_the_same_tracks(self, novelty):
        first = await run_pipeline(
            [TEST_SEED], "key", None, novelty, make_clients()
        )
        second = await run_pipeline(
            [TEST_SEED], "key", None, novelty, make_clients()
        )
        assert fingerprint(first) == fingerprint(second)

    @pytest.mark.parametrize("mood", MOODS)
    async def test_each_mood_reproduces_its_own_ordering(self, mood):
        first = await run_pipeline(
            [TEST_SEED], "key", mood, 0.5, make_clients()
        )
        second = await run_pipeline(
            [TEST_SEED], "key", mood, 0.5, make_clients()
        )
        assert fingerprint(first) == fingerprint(second)

    # The property the canonical pre sort exists for u/pstream pages arriving
    # in a different sequence must not move a track in the result
    @pytest.mark.parametrize("novelty", NOVELTY_LEVELS)
    async def test_upstream_arrival_order_does_not_change_the_result(
        self, novelty
    ):
        default = await run_pipeline(
            [TEST_SEED], "key", None, novelty, make_clients()
        )
        shuffled = await run_pipeline(
            [TEST_SEED], "key", None, novelty, make_reversed_clients()
        )
        assert fingerprint(default) == fingerprint(shuffled)
