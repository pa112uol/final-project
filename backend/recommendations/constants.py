RECOMMENDATION_LIMIT = 10
# The two tag sources report counts in incommensurable units: Last.fm
# normalizes per track (its top tag is always 100, so a count is really a
# percentage), while ListenBrainz returns raw vote totals. Each source is
# scaled to [0,1] against its own maximum before merging and blended by this
# weight, so the source ratio is one explicit number rather than an artifact
# of two different counting schemes.
LB_SOURCE_WEIGHT = 0.6
# Blended weights are fractions; rescale to Last.fm's familiar 0-100 range so
# tag counts stay readable in logs
TAG_COUNT_SCALE = 100
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
