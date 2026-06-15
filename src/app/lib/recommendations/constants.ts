export const RECOMMENDATION_LIMIT = 10;
// LB tag counts are ~1-10; LF tag counts go up to 100. Scale LB up so they
// dominate TF in buildTagWeights while still letting LF mood/vibe tags supplement.
export const LB_TAG_SCALE = 15;
export const TOP_TAGS_COUNT = 6;
export const ARTISTS_PER_TAG = 30;
export const TOP_ARTISTS_COUNT = 15;
export const TRACKS_PER_ARTIST = 5;
export const MOOD_MULTIPLIER = 1.5;
export const MMR_LAMBDA = 0.7;
export const MAX_TRACKS_PER_ARTIST = 2;

// Within recording-level obscurity: listen count (scale) vs user count (breadth)
export const LISTEN_VS_USER_BLEND = 0.6;
// Recording-level obscurity vs artist-level obscurity fallback
export const REC_VS_ARTIST_BLEND = 0.7;
// Artist-level tag relevance vs track-level tag relevance
export const ARTIST_VS_TRACK_TAG_BLEND = 0.6;

