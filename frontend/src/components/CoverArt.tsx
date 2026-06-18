import { useState, useEffect } from "react";

interface CoverArtProps {
  mbid: string;
  className?: string;
}

export default function CoverArt({
  mbid,
  className = "w-16 h-16 rounded-lg",
}: CoverArtProps) {
  const [url, setUrl] = useState<string | null>(null);
  const [fetching, setFetching] = useState(true);
  const [imgReady, setImgReady] = useState(false);

  useEffect(() => {
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
  }, [mbid]);

  const showSkeleton = fetching || (!!url && !imgReady);
  const showPlaceholder = !fetching && !url;

  return (
    <div className={`${className} relative flex-shrink-0 overflow-hidden`}>
      {/* Skeleton overlay, shown while fetching URL or while image is loading */}
      {showSkeleton && (
        <div className="absolute inset-0 bg-gray-700 animate-pulse" />
      )}

      {/* Music note, shown when no cover art found */}
      {showPlaceholder && (
        <div className="absolute inset-0 bg-gray-700 flex items-center justify-center">
          <svg
            className="w-1/2 h-1/2 text-gray-500"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
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

      {/* Image, always mounted once URL is set so onLoad/onError can fire */}
      {url && (
        <img
          src={url}
          alt=""
          className={`absolute inset-0 w-full h-full object-cover transition-opacity duration-300 ${imgReady ? "opacity-100" : "opacity-0"}`}
          onLoad={() => setImgReady(true)}
          onError={() => {
            setUrl(null);
          }}
        />
      )}
    </div>
  );
}
