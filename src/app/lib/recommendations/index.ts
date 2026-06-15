import {
  fetchTrackTags,
  fetchTrackTagsOnly,
  fetchTagArtists,
} from "@/app/lib/lastfm";
import {
  fetchArtistPopularity,
  fetchArtistTopRecordings,
  fetchRecordingTags,
} from "@/app/lib/listenbrainz";
import { resolveArtistMbid } from "@/app/lib/mb";
import { getStreamingLinks } from "@/app/lib/streaming";
import { runPipeline } from "./pipeline";
import type { PipelineClients, Seed, Track } from "./types";

export type { Seed, Track } from "./types";
export { MOOD_TAGS } from "./tags";

const realClients: PipelineClients = {
  fetchTagArtists,
  fetchTrackTags,
  fetchTrackTagsOnly,
  fetchArtistTopRecordings,
  resolveArtistMbid,
  fetchRecordingTags,
  fetchArtistPopularity,
  getStreamingLinks,
};

export function getRecommendations(
  seeds: Seed[],
  apiKey: string,
  mood?: string,
  novelty = 0,
): Promise<Track[]> {
  return runPipeline(seeds, apiKey, mood, novelty, realClients);
}
