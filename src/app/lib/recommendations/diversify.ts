import type { ScoredCandidate } from "./types";
import { MMR_LAMBDA } from "./constants";

export function tokenize(tags: string[]): Set<string> {
  const tokens = new Set<string>();
  for (const tag of tags) {
    for (const word of tag.toLowerCase().split(/\s+/)) {
      if (word) tokens.add(word);
    }
  }
  return tokens;
}

export function jaccardSets(a: Set<string>, b: Set<string>): number {
  if (a.size === 0 || b.size === 0) return 0;
  let intersection = 0;
  for (const token of a) {
    if (b.has(token)) intersection++;
  }
  return intersection / (a.size + b.size - intersection);
}

export function mmrSelect(
  ranked: ScoredCandidate[],
  k: number,
): ScoredCandidate[] {
  const remaining = ranked.map((c) => ({ c, tokens: tokenize(c.tags) }));
  const selected: ScoredCandidate[] = [];
  const selectedTokens: Set<string>[] = [];

  while (selected.length < k && remaining.length > 0) {
    let bestIdx = 0;
    let bestScore = -Infinity;
    for (let i = 0; i < remaining.length; i++) {
      const { c, tokens } = remaining[i];
      const maxSim =
        selectedTokens.length === 0
          ? 0
          : Math.max(...selectedTokens.map((st) => jaccardSets(tokens, st)));
      const score = MMR_LAMBDA * c.finalScore - (1 - MMR_LAMBDA) * maxSim;
      if (score > bestScore) {
        bestScore = score;
        bestIdx = i;
      }
    }
    selected.push(remaining[bestIdx].c);
    selectedTokens.push(remaining[bestIdx].tokens);
    remaining.splice(bestIdx, 1);
  }
  return selected;
}
