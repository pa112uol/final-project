import type { StreamingLinks } from "@/app/lib/streaming";
import type { LFTag, LFArtist } from "@/app/lib/lastfm";
import type { LBRecording } from "@/app/lib/listenbrainz";

export type { LFTag, LFArtist, LBRecording, StreamingLinks };

export interface Seed {
  mbid: string;
  title: string;
  artist: string;
}

export interface Track {
  mbid: string;
  title: string;
  artist: string;
  artistMbid: string;
  durationMs: number | null;
  firstReleaseDate: string | null;
  releases: { mbid: string; title: string; date?: string }[];
  streaming: StreamingLinks;
  relevanceScore: number;
  noveltyScore: number;
}

export interface Candidate {
  title: string;
  artist: string;
  artistMbid: string;
  mbid: string;
  durationMs: number | null;
  tagWeightSum: number;
  trackTagScore: number;
  listenCount: number;
  userCount: number;
  artistListenCount: number;
  tags: string[];
}

export interface ScoredCandidate extends Candidate {
  finalScore: number;
  relevanceScore: number;
  noveltyScore: number;
}

export interface PipelineClients {
  fetchTagArtists(
    tag: string,
    page: number,
    limit: number,
    apiKey: string,
  ): Promise<LFArtist[]>;
  fetchArtistTopRecordings(
    mbid: string,
    limit: number,
  ): Promise<LBRecording[]>;
  resolveArtistMbid(name: string): Promise<string>;
  fetchRecordingTags(mbid: string): Promise<{ name: string; count: number }[]>;
  fetchTrackTags(
    title: string,
    artist: string,
    apiKey: string,
    mbid?: string,
  ): Promise<LFTag[]>;
  fetchTrackTagsOnly(
    title: string,
    artist: string,
    apiKey: string,
    mbid?: string,
  ): Promise<LFTag[]>;
  fetchArtistPopularity(mbids: string[]): Promise<Map<string, number>>;
  getStreamingLinks(artist: string, title: string): Promise<StreamingLinks>;
}
