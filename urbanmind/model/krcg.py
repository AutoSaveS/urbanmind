"""Stage 2: knowledge retrieval and constraint grounding (KRCG).

The mechanism is retrieval-conditioned *constraint grounding* -- analogous to but
distinct from retrieval-augmented text generation. Queries are built from local
context (LCZ, Koeppen class, building height, sky-view factor, plan-area density);
retrieval draws from a Physical Constraint Library and a Downscaling Parameter
Library, and the top-k entries gate the constraint projection.
"""

from dataclasses import dataclass, field

import numpy as np


@dataclass
class KnowledgeEntry:
    entry_id: str
    doi: str
    library: str                 # "constraint" or "downscaling"
    embedding: np.ndarray        # context embedding
    payload: dict = field(default_factory=dict)  # equation form, parameters, bounds


@dataclass
class KnowledgeLibrary:
    entries: list[KnowledgeEntry]

    def matrix(self) -> np.ndarray:
        return np.stack([e.embedding for e in self.entries])


class KRCGRetriever:
    """Cosine-similarity top-k retrieval with similarity weights.

    Retrieval-confidence weights w_k are reported with every correction so that
    unsupported extrapolations can be distinguished from strongly matched priors.
    """

    def __init__(self, library: KnowledgeLibrary, k: int = 5):
        self.library = library
        self.k = k
        m = library.matrix()
        self._normed = m / np.linalg.norm(m, axis=1, keepdims=True)

    def retrieve(self, context: np.ndarray) -> list[tuple[KnowledgeEntry, float]]:
        q = context / np.linalg.norm(context)
        sims = self._normed @ q
        top = np.argsort(sims)[::-1][: self.k]
        weights = np.clip(sims[top], 0, None)
        total = weights.sum()
        if total > 0:
            weights = weights / total
        return [(self.library.entries[i], float(w)) for i, w in zip(top, weights)]

    def match_record(self, context: np.ndarray) -> dict:
        """Loggable retrieval-match record (entry ids, DOIs, weights)."""
        matches = self.retrieve(context)
        return {
            "entries": [e.entry_id for e, _ in matches],
            "dois": [e.doi for e, _ in matches],
            "weights": [w for _, w in matches],
        }
