from fastapi import APIRouter, Query

router = APIRouter()


@router.get("/search/")
async def search(q: str = Query(default="")) -> dict:
    query = q.strip()
    if not query:
        return {"results": []}

    # Imported lazily so tests can patch clients.musicbrainz.search_tracks
    from clients.musicbrainz import search_tracks

    tracks = await search_tracks(query)
    results = [
        {
            "type": "track",
            "mbid": t["mbid"],
            "label": t["title"],
            "sub": t["artist"],
            "album": t.get("album"),
            "releaseType": t.get("release_type"),
            "year": t.get("year"),
        }
        for t in tracks
    ]
    return {"results": results}
