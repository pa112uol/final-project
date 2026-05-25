"use client";

import dynamic from "next/dynamic";

const TracksList = dynamic(() => import("./TracksList"), { ssr: false });

interface Seed {
  t: string;
  a: string;
}

export default function TracksListWrapper({ selections }: { selections?: string }) {
  let seeds: Seed[] = [];
  if (selections) {
    try {
      seeds = JSON.parse(selections);
    } catch {}
  }

  if (seeds.length > 0) {
    const params = new URLSearchParams();
    seeds.forEach((s) => {
      params.append("title", s.t);
      params.append("artist", s.a);
    });
    return <TracksList url={`/api/recommendations?${params.toString()}`} mode="recommendations" />;
  }

  return <TracksList />;
}
