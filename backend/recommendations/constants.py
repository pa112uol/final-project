RECOMMENDATION_LIMIT = 10
# The two tag sources count in incommensurable units: Last.fm normalizes per
# track, so its top tag is always 100 and a count is really a percentage, while
# ListenBrainz returns raw vote totals. Each is scaled to [0,1] against its own
# maximum before merging so this weight makes the source ratio one explicit
# number rather than an artifact of two counting schemes
LB_SOURCE_WEIGHT = 0.6
# Blended weights are fractions... rescale to Last.fm's familiar 0-100 range so
# tag counts stay readable in logs
TAG_COUNT_SCALE = 100
TOP_TAGS_COUNT = 6
ARTISTS_PER_TAG = 30
# Widening the pool pays off along the artist axis only. More tracks per artist
# measurably hurt, since each artist's best two then score higher and the
# strongest artists monopolise the final slots instead of more artists
# appearing. On a trip hop query, 20x8 gave 5 distinct artists at 0.12
# intra-list diversity against 6 at 0.42 for 20x5, and past 20 artists nothing
# changed at all
TOP_ARTISTS_COUNT = 20
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

# How many of a seed's strongest tags define what is "distinctive" about it.
# Differencing the full tag lists would push distinctiveness into a long tail
# of rare tags no candidate carries whereas the top tags characterise a seed.
# Selection and evaluation share it so objective and measurement stay aligned
DISTINCTIVE_TOP_N = 10
