RECOMMENDATION_LIMIT = 10
# LB tag counts are roughly 1-10, LF tag counts go up to 100.
# Scale LB up so they dominate TF in build_tag_weights while still letting
# LF mood/vibe tags supplement
LB_TAG_SCALE = 15
TOP_TAGS_COUNT = 6
ARTISTS_PER_TAG = 30
TOP_ARTISTS_COUNT = 15
TRACKS_PER_ARTIST = 5
MOOD_MULTIPLIER = 1.5
MMR_LAMBDA = 0.7
MAX_TRACKS_PER_ARTIST = 2

# Within recording-level obscurity: listen count (scale) vs user count (breadth)
LISTEN_VS_USER_BLEND = 0.6
# Recording-level obscurity vs artist-level obscurity fallback
REC_VS_ARTIST_BLEND = 0.7
# Artist-level tag relevance vs track-level tag relevance
ARTIST_VS_TRACK_TAG_BLEND = 0.6
