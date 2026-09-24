from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
from pathlib import Path

from evaluation.retrieval_metrics import fold_text, title_key
from evaluation.retrieval_ranking_eval import upstream_failures

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
RETRY_WAIT_SECONDS = 5
SAVE_EVERY = 25

# Where a MusicBrainz credit moves on from its lead artist to the next one
CREDIT_JOIN_PATTERN = re.compile(
    r"\s*(?:,|&|\band\b|\bfeat\.?|\bft\.?|\bfeaturing\b|\bwith\b|\bx\b|\bvs\.?)\s+",
    re.IGNORECASE,
)


class ResolutionIncomplete(RuntimeError):
    pass


# "&" and "and" are the same word in artist names, as in Simon & Garfunkel
def fold_artist(name: str) -> str:
    return fold_text(re.sub(r"\s*&\s*", " and ", name))


# The whole credit must match, or its lead artist when MusicBrainz credits a
# collaboration such as "A & B" that the playlist lists as just "A"
def artist_matches(wanted: str, credited: str) -> bool:
    target = fold_artist(wanted)
    if not target:
        return False
    lead = CREDIT_JOIN_PATTERN.split(credited, maxsplit=1)[0]
    return target in (fold_artist(credited), fold_artist(lead))


def is_match(seed: dict, result: dict) -> bool:
    return artist_matches(seed["artist"], result.get("artist", "")) and (
        title_key("", seed["title"])[1]
        == title_key("", result.get("title", ""))[1]
    )


# The first search result that matches, as a user would pick it, or "" for none
def pick_mbid(seed: dict, results: list[dict]) -> str:
    for result in results:
        if result.get("mbid") and is_match(seed, result):
            return result["mbid"]
    return ""


def seed_key(seed: dict) -> str:
    return seed.get("track_id") or f"{seed['artist']}|||{seed['title']}"


# One lookup. Retries when the search logged an upstream failure, since the
# search client returns an empty list for both a failure and a genuine miss
async def resolve_seed(seed: dict, search, sleep=asyncio.sleep) -> str:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        with upstream_failures() as failures:
            results = await search(seed["title"], seed["artist"])
        if not failures:
            return pick_mbid(seed, results)
        logger.warning(
            "search failed for %s, attempt %d", seed_key(seed), attempt
        )
        await sleep(RETRY_WAIT_SECONDS * attempt)
    raise ResolutionIncomplete(f"search kept failing for {seed_key(seed)}")


def unique_seeds(cases: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for case in cases:
        for seed in case["seeds"]:
            seen.setdefault(seed_key(seed), seed)
    return list(seen.values())


# Writes every resolved MBID into each case that uses the seed, so one-seed and
# two-seed cases sharing a seed always agree
def apply_resolutions(cases: list[dict], resolved: dict[str, str]) -> None:
    for case in cases:
        for seed in case["seeds"]:
            mbid = resolved.get(seed_key(seed))
            if mbid:
                seed["recording_mbid"] = mbid


def resolution_summary(seeds: list[dict], resolved: dict[str, str]) -> dict:
    return {
        "method": "app MusicBrainz search, first result matching artist and title",
        "seeds": len(seeds),
        "resolved": sum(bool(resolved.get(seed_key(s))) for s in seeds),
        "unresolved": sorted(
            f"{s['artist']} - {s['title']}"
            for s in seeds
            if not resolved.get(seed_key(s))
        ),
        "by_seed": resolved,
    }


def save(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


async def resolve_catalogue(path: Path, search, sleep=asyncio.sleep) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    seeds = unique_seeds(payload["cases"])
    resolved: dict[str, str] = dict(
        payload.get("seed_resolution", {}).get("by_seed", {})
    )
    pending = [seed for seed in seeds if seed_key(seed) not in resolved]
    try:
        for position, seed in enumerate(pending, 1):
            resolved[seed_key(seed)] = await resolve_seed(seed, search, sleep)
            if position % SAVE_EVERY == 0:
                logger.info("resolved %d/%d", position, len(pending))
                payload["seed_resolution"] = resolution_summary(seeds, resolved)
                save(path, payload)
    finally:
        apply_resolutions(payload["cases"], resolved)
        payload["seed_resolution"] = resolution_summary(seeds, resolved)
        save(path, payload)
    return payload["seed_resolution"]


def main() -> None:
    from clients.musicbrainz import search_tracks_fields

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalogue", type=Path, required=True)
    args = parser.parse_args()
    try:
        summary = asyncio.run(
            resolve_catalogue(args.catalogue, search_tracks_fields)
        )
    except ResolutionIncomplete as exc:
        raise SystemExit(f"{exc}. Progress is saved, rerun to resume") from exc
    logger.info(
        "%d of %d seeds resolved, %d unresolved",
        summary["resolved"],
        summary["seeds"],
        len(summary["unresolved"]),
    )


if __name__ == "__main__":
    main()
