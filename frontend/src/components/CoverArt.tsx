import { useState, useEffect, useRef, useCallback } from "react";

interface CoverArtProps {
  mbid: string;
  artworkUrl?: string | null;
  className?: string;
  // True while mbid is still the source's stale value, not yet patched by the
  // lazy recording lookup. Holds off the mbid-driven fetch until it lands.
  pending?: boolean;
  // The release the recording lookup already resolved, if any, so
  // /api/coverart/ can skip its own MusicBrainz release lookup.
  releaseMbid?: string;
}

export default function CoverArt({
  mbid,
  artworkUrl,
  className = "w-16 h-16 rounded-lg",
  pending = false,
  releaseMbid,
}: CoverArtProps) {
  const [url, setUrl] = useState<string | null>(artworkUrl ?? null);
  const [fetching, setFetching] = useState(!artworkUrl);
  const [imgReady, setImgReady] = useState(false);
  const imgRef = useRef<HTMLImageElement>(null);

  const handleLoad = useCallback(() => setImgReady(true), []);

  // ArtworkUrl is a pre-resolved image, so it skips the /api/coverart request entirely.
  // Keyed only on artworkUrl, not mbid, so a later mbid patch doesn't re-fade a loaded image.
  useEffect(() => {
    if (!artworkUrl) return;
    setUrl(artworkUrl);
    setFetching(false);
    setImgReady(false);
  }, [artworkUrl]);

  // Falls back to the mbid-driven fetch only when there's no iTunes artwork
  useEffect(() => {
    if (artworkUrl) return;

    if (pending) {
      setFetching(true);
      return;
    }

    let cancelled = false;
    setUrl(null);
    setFetching(true);
    setImgReady(false);
    const params = new URLSearchParams({ mbid });
    if (releaseMbid) params.set("releaseMbid", releaseMbid);
    fetch(`/api/coverart/?${params.toString()}`)
      .then((res) => (res.ok ? res.json() : Promise.reject()))
      .then((data) => {
        if (!cancelled && data?.url) setUrl(data.url);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setFetching(false);
      });
    return () => {
      cancelled = true;
    };
  }, [mbid, artworkUrl, pending, releaseMbid]);

  // Handle images already in the browser cache
  useEffect(() => {
    if (url && imgRef.current?.complete) setImgReady(true);
  }, [url]);

  const showSkeleton = fetching || (!!url && !imgReady);
  const showPlaceholder = !fetching && !url;

  return (
    <div className={`${className} relative flex-shrink-0 overflow-hidden`}>
      {showSkeleton && (
        <div className="absolute inset-0 bg-bg-raised animate-pulse" />
      )}

      {showPlaceholder && (
        <div className="absolute inset-0 bg-bg-raised flex items-center justify-center">
          <svg
            className="w-1/2 h-1/2 text-text-muted"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3"
            />
          </svg>
        </div>
      )}

      {url && (
        <img
          ref={imgRef}
          src={url}
          alt=""
          className={`absolute inset-0 w-full h-full object-cover transition-opacity duration-300 ${imgReady ? "opacity-100" : "opacity-0"}`}
          onLoad={handleLoad}
          onError={() => setUrl(null)}
        />
      )}
    </div>
  );
}

