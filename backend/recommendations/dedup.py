import re
from .types import Candidate
from .utils import get_field


# Strip edition/version suffixes (" - Remastered", " (Live)", " [Bonus Track]"),
# featuring credits (" feat. X", " ft. X", " featuring X"), and part indicators
# (", Part 2", ", Pt. II") so variant recordings collapse to a single dedup key.
# Space before the delimiter avoids clipping hyphenated titles like "Drive-In".
# Requiring a dot for bare "ft" avoids false positives like "12 sq ft room"
def normalize_title(title: str) -> str:
    result = title.lower()
    result = re.sub(r" [-(\[].*$", "", result)
    result = re.sub(r" (feat\.?|ft\.|featuring)\s.*$", "", result)
    result = re.sub(r",?\s+(part|pt\.?)\s+\w+$", "", result)
    return result.strip()


def titles_overlap(a: str, b: str) -> bool:
    if a == b:
        return True
    longer, shorter = (a, b) if len(a) >= len(b) else (b, a)
    if longer.startswith(shorter) and re.match(
        r"^ [-(\[]", longer[len(shorter) :]
    ):
        return True
    return False


def filter_seeds(
    candidates: list,
    seeds: list,
    exclude_seed_artists: bool = True,
) -> list:
    seed_artists = {get_field(s, "artist").lower() for s in seeds}
    seed_titles = [get_field(s, "title").lower() for s in seeds]

    def keep(c: Candidate) -> bool:
        artist = get_field(c, "artist").lower()
        title = get_field(c, "title").lower()
        if exclude_seed_artists and artist in seed_artists:
            return False
        return not any(titles_overlap(t, title) for t in seed_titles)

    return [c for c in candidates if keep(c)]


def deduplicate_by_mbid(candidates: list) -> list:
    seen_mbids = set()
    result = []
    for c in candidates:
        mbid = get_field(c, "mbid")
        if not mbid:
            result.append(c)
            continue
        if mbid in seen_mbids:
            continue
        seen_mbids.add(mbid)
        result.append(c)
    return result


def _title_variant_wins(candidate, prev) -> bool:
    has_mbid = bool(get_field(candidate, "mbid"))
    prev_has_mbid = bool(get_field(prev, "mbid"))
    if has_mbid != prev_has_mbid:
        return has_mbid
    return get_field(candidate, "listen_count") > get_field(
        prev, "listen_count"
    )


# Collapse variant recordings (remaster/live/single editions) that share a
# normalized title + artist but carry distinct MBIDs which deduplicate_by_mbid
# cannot catch. Keep the variant with an MBID (enables popularity lookup),
# then the one with more listens.
def deduplicate_by_title(candidates: list) -> list:
    kept = {}
    for c in candidates:
        title = get_field(c, "title")
        artist = get_field(c, "artist")
        norm_key = f"{normalize_title(title)}|||{artist.lower()}"
        prev = kept.get(norm_key)
        if prev is None or _title_variant_wins(c, prev):
            kept[norm_key] = c

    return list(kept.values())
