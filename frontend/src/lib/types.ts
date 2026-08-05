// A track picked as input to the recommender. Chosen on the search page and
// carried to the results page in the URL.
export interface Seed {
  mbid: string;
  title: string;
  artist: string;
}
