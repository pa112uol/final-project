"use client";

import dynamic from "next/dynamic";

const TracksList = dynamic(() => import("./TracksList"), { ssr: false });

interface TracksListWrapperProps {
  selections?: string; // future use: "type:mbid,type:mbid,..."
}

export default function TracksListWrapper({ selections: _selections }: TracksListWrapperProps) {
  return <TracksList />;
}
