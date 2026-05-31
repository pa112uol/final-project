const SPARQL_ENDPOINT = "https://query.wikidata.org/sparql";
const USER_AGENT = "NextTrack/1.0 (https://github.com/nexttrack)";
const MBID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

interface SparqlResults {
  results: { bindings: { genreLabel?: { value: string } }[] };
}

export async function fetchArtistGenres(artistMbids: string[]): Promise<string[]> {
  const validMbids = artistMbids.filter((id) => MBID_RE.test(id));
  if (validMbids.length === 0) return [];

  const values = validMbids.map((id) => `"${id}"`).join(" ");
  const query = `SELECT DISTINCT ?genreLabel WHERE {
  VALUES ?mbid { ${values} }
  ?artist wdt:P434 ?mbid .
  ?artist wdt:P136 ?genre .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
}`;

  try {
    const url = new URL(SPARQL_ENDPOINT);
    url.searchParams.set("query", query);
    url.searchParams.set("format", "json");

    const res = await fetch(url.toString(), {
      headers: { "User-Agent": USER_AGENT, Accept: "application/sparql-results+json" },
    });
    if (!res.ok) return [];

    const data = (await res.json()) as SparqlResults;
    return data.results.bindings
      .map((b) => b.genreLabel?.value ?? "")
      .filter(Boolean)
      .map((label) => label.toLowerCase().replace(/-/g, " ").trim());
  } catch {
    return [];
  }
}
