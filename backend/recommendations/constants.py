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
# Mood is added after the novelty blend rather than folded into relevance, so a
# mood request still steers results at novelty=1 where the relevance term
# carries no weight at all. At 1.0 a full match/conflict (mood_score +-1) can
# overturn a same strength runner up outright, letting mood change the top pick
# itself rather than only reordering the tail below it. A top match still
# holds its spot against a mood it already fits equally well or better -
# demoting an already mood-appropriate result would be wrong, not drastic.
MOOD_SCORE_WEIGHT = 1.0
# How hard a contradicting mood tag ("aggressive" under a chill request) counts
# against a candidate, relative to a matching one. Below 1.0 because an
# opposing tag is weaker evidence than a confirming one: tracks carry many tags
# and one stray descriptor should demote, not disqualify
MOOD_CONFLICT_PENALTY = 0.5
MMR_LAMBDA = 0.7
MAX_TRACKS_PER_ARTIST = 2

# Why a candidate won its slot. MMR order is not final_score order, so a client
# showing only relevance/novelty can display a track above one with visibly
# better bars and look broken. These name the actual reason: TOP_MATCH means it
# had the best score among the candidates still in play, FOR_VARIETY means the
# diversity term lifted it past higher scoring but more redundant ones.
SELECTION_TOP_MATCH = "top_match"
SELECTION_FOR_VARIETY = "for_variety"
SELECTION_FOR_SEED_COVERAGE = "for_seed_coverage"

# Within recording-level obscurity: listen count (scale) vs user count (breadth)
LISTEN_VS_USER_BLEND = 0.6
# Recording-level obscurity vs artist-level obscurity fallback
REC_VS_ARTIST_BLEND = 0.7
# Artist-level tag relevance vs track-level tag relevance
ARTIST_VS_TRACK_TAG_BLEND = 0.6

# Enrichment costs one HTTP call per candidate (~91 at novelty 0, ~182 at
# novelty 1, to return 10 tracks), so these cap how much gets enriched.
# The cap is on artists, not tracks: recordings arrive untagged from Last.fm's
# top-tracks endpoint, so before enrichment an artist's tracks differ only in
# listen count and ranking tracks just ranks artists. Instead pick the top
# artists (an artist-level choice from artist-level signal), then keep the
# most listened tracks of each.
ENRICH_TOP_ARTISTS = 15
# Above MAX_TRACKS_PER_ARTIST so the artist cap still has a choice to make
ENRICH_TRACKS_PER_ARTIST = 3

# Enrichment does two jobs that can be paid for separately: tags for selection,
# and tags on the tracks actually returned. Cutting the pre-selection pass cuts
# both, so results come back with about a third of the tags - measured 9.1 -> 2.9
# tags per returned track. The modes split the two jobs apart:
# all - enrich every candidate before selection (most calls, richest output)
# budget - enrich a capped subset before selection (fewer calls, thin output)
# final - enrich only the selected tracks (fewest calls, rich output, but
#   selection uses whatever tags the sources already provided)
# hybrid - capped subset before selection, then top up the winners
# auto - pick per request from novelty
ENRICH_MODE_ALL = "all"
ENRICH_MODE_BUDGET = "budget"
ENRICH_MODE_FINAL = "final"
ENRICH_MODE_HYBRID = "hybrid"
ENRICH_MODE_AUTO = "auto"
ENRICH_MODES = (
    ENRICH_MODE_ALL,
    ENRICH_MODE_BUDGET,
    ENRICH_MODE_FINAL,
    ENRICH_MODE_HYBRID,
    ENRICH_MODE_AUTO,
)
DEFAULT_ENRICH_MODE = ENRICH_MODE_AUTO

# Modes that leave enrichment for the selected tracks to pick up afterwards
POST_SELECTION_ENRICH_MODES = (ENRICH_MODE_FINAL, ENRICH_MODE_HYBRID)

# Above this novelty, auto mode switches from hybrid to final. High novelty
# fetches a deeper, more obscure pool, and Last.fm has few tags for obscure
# recordings. Measured over 6 queries, enriching every candidate cost 178 calls
# and still gave only 2.3 tags per returned track, the same as every cheaper
# mode
HIGH_NOVELTY_ENRICH_THRESHOLD = 0.75

# How many of a seed's strongest tags define what is "distinctive" about it.
# Differencing the full tag lists would push distinctiveness into a long tail
# of rare tags no candidate carries whereas the top tags characterise a seed.
# Selection and evaluation share it so objective and measurement stay aligned
DISTINCTIVE_TOP_N = 10
