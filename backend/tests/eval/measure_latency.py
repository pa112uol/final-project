import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx
import redis

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from bench.load import run_load

BASE = os.environ.get("EVAL_BASE_URL", "http://127.0.0.1:5057")
REDIS_HOST = os.environ.get("EVAL_REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("EVAL_REDIS_PORT", "6379"))
REDIS_DB = int(os.environ.get("EVAL_REDIS_DB", "15"))

NOVELTY = 0.5
WARM_SEQUENTIAL_REQUESTS = 30
WARM_CONCURRENT_REQUESTS = 30
WARM_CONCURRENCY = 5
MUSICBRAINZ_DELAY_S = 1.2

# The server under test must run with RECS_STREAMING_LINKS=0, so the timings
# measure the recommendation pipeline rather than the per-track link fan-out
STREAMING_LINKS_ENV = "RECS_STREAMING_LINKS"

SEED_PAIRS = [
    [("Only Shallow", "My Bloody Valentine"), ("Vapour Trail", "Ride")],
    [("Space Song", "Beach House"), ("Heaven or Las Vegas", "Cocteau Twins")],
    [("Teardrop", "Massive Attack"), ("Glory Box", "Portishead")],
    [
        ("Superstition", "Stevie Wonder"),
        ("Love Will Tear Us Apart", "Joy Division"),
    ],
    [("Come as You Are", "Nirvana"), ("Black Hole Sun", "Soundgarden")],
    [("Avril 14th", "Aphex Twin"), ("An Ending (Ascent)", "Brian Eno")],
]


def resolve_seed(client: httpx.Client, title: str, artist: str) -> dict:
    res = client.get(
        "https://musicbrainz.org/ws/2/recording",
        params={
            "query": f'recording:"{title}" AND artist:"{artist}"',
            "fmt": "json",
            "limit": "3",
        },
        headers={"User-Agent": "nexttrack-eval/1.0"},
    )
    res.raise_for_status()
    time.sleep(MUSICBRAINZ_DELAY_S)
    recordings = res.json().get("recordings") or []
    if not recordings:
        raise ValueError(f"no MusicBrainz hit for {title} by {artist}")
    return {"mbid": recordings[0]["id"], "title": title, "artist": artist}


def build_url(seeds: list) -> str:
    parts = [f"novelty={NOVELTY}"]
    for seed in seeds:
        parts.append(f"mbid={seed['mbid']}")
        parts.append(f"title={seed['title']}")
        parts.append(f"artist={seed['artist']}")
    return f"{BASE}/api/recommendations/?" + "&".join(parts).replace(" ", "+")


def cache_counters(conn: redis.Redis) -> tuple:
    info = conn.info("stats")
    return info["keyspace_hits"], info["keyspace_misses"]


# A populated iTunes or YouTube field means the server ran the per-track link
# lookups, which would put upstream link latency into the reported timings
def assert_streaming_lookups_disabled(tracks: list) -> None:
    looked_up = [
        t
        for t in tracks
        if (t.get("streaming") or {}).get("appleMusic")
        or (t.get("streaming") or {}).get("youtubeVideoId")
    ]
    if looked_up:
        raise RuntimeError(
            f"{len(looked_up)} tracks carry streaming links. "
            f"Restart the server with {STREAMING_LINKS_ENV}=0 before timing."
        )


def summarise(summary) -> dict:
    return {
        "requests": summary.total_requests,
        "errors": summary.error_count,
        "p50_ms": round(summary.p50_ms),
        "p95_ms": round(summary.p95_ms),
        "mean_ms": round(summary.mean_ms),
        "min_ms": round(summary.min_ms),
        "max_ms": round(summary.max_ms),
    }


def main() -> None:
    conn = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)
    conn.flushdb()

    with httpx.Client(timeout=60) as client:
        urls = [
            build_url([resolve_seed(client, t, a) for t, a in pair])
            for pair in SEED_PAIRS
        ]

    # Sanity check one response before timing anything
    with httpx.Client(timeout=60) as client:
        probe = client.get(urls[0])
        probe.raise_for_status()
        tracks = probe.json()["tracks"]
        track_count = len(tracks)
    assert_streaming_lookups_disabled(tracks)
    conn.flushdb()

    hits_before, misses_before = cache_counters(conn)
    cold = asyncio.run(
        run_load(
            urls,
            concurrency=1,
            requests=len(urls),
            warmup=0,
            label="cold",
            timeout_s=60,
        )
    )
    hits_cold, misses_cold = cache_counters(conn)

    warm_seq = asyncio.run(
        run_load(
            urls,
            concurrency=1,
            requests=WARM_SEQUENTIAL_REQUESTS,
            warmup=0,
            label="warm",
        )
    )
    hits_warm, misses_warm = cache_counters(conn)

    warm_conc = asyncio.run(
        run_load(
            urls,
            concurrency=WARM_CONCURRENCY,
            requests=WARM_CONCURRENT_REQUESTS,
            warmup=0,
            label="warm-concurrent",
        )
    )
    hits_conc, misses_conc = cache_counters(conn)

    out = {
        "probe_track_count": track_count,
        "cold": summarise(cold),
        "warm_sequential": summarise(warm_seq),
        "warm_concurrent": summarise(warm_conc),
        "cold_pass_cache": {
            "hits": hits_cold - hits_before,
            "misses": misses_cold - misses_before,
        },
        "warm_pass_cache": {
            "hits": hits_warm - hits_cold,
            "misses": misses_warm - misses_cold,
        },
        "warm_concurrent_pass_cache": {
            "hits": hits_conc - hits_warm,
            "misses": misses_conc - misses_warm,
        },
        "keys_in_cache": conn.dbsize(),
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
