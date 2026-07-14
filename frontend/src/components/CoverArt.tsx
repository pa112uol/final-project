import { useState, useEffect, useRef, useCallback } from "react";

interface CoverArtProps {
  mbid: string;
  artworkUrl?: string | null;
  className?: string;
}

export default function CoverArt({
  mbid,
  artworkUrl,
  className = "w-16 h-16 rounded-lg",
}: CoverArtProps) {
  const [url, setUrl] = useState<string | null>(artworkUrl ?? null);
  const [fetching, setFetching] = useState(!artworkUrl);
  const [imgReady, setImgReady] = useState(false);
  const imgRef = useRef<HTMLImageElement>(null);

  const handleLoad = useCallback(() => setImgReady(true), []);

  // ArtworkUrl is a pre-resolved iTunes image that ships with
  // the track already, so it skips the /api/coverart request entirely.
  // Falling back to the mbid-driven fetch only happens when it's absent.
  useEffect(() => {
    if (artworkUrl) {
      setUrl(artworkUrl);
      setFetching(false);
      setImgReady(false);
      return;
    }

    let cancelled = false;
    setUrl(null);
    setFetching(true);
    setImgReady(false);
    fetch(`/api/coverart/?mbid=${encodeURIComponent(mbid)}`)
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
  }, [mbid, artworkUrl]);

  // Handle images already in the browser cache
  useEffect(() => {
    if (url && imgRef.current?.complete) setImgReady(true);
  }, [url]);

  const showSkeleton = fetching || (!!url && !imgReady);
  const showPlaceholder = !fetching && !url;

  return (
    <div className={`${className} relative flex-shrink-0 overflow-hidden`}>
      {showSkeleton && (
        <div className="absolute inset-0 bg-border-default animate-pulse" />
      )}

      {showPlaceholder && (
        <div className="absolute inset-0 bg-border-default flex items-center justify-center">
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

