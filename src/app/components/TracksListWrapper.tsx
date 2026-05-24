"use client";

import dynamic from "next/dynamic";

const TracksList = dynamic(() => import("./TracksList"), { ssr: false });

export default function TracksListWrapper() {
  return <TracksList />;
}
