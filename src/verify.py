"""Check a finished answer against the knowledge that was sent.

Pure functions. No I/O. A sentence is unsupported when its content-word overlap
with the best knowledge window is below SUPPORT_THRESHOLD, or when it contains
a claim token or a characterization word the knowledge does not.

A window is one knowledge sentence, or two or three consecutive sentences.
Windows stay inside one entry or one facts-file section. They do not cross
an entry break or a markdown heading.

What this cannot judge: a word that also appears somewhere in the knowledge
("a few" versus "every", or "often" added to a real cruise sentence when that
entry already says "often") can make an invented sentence look supported.
Overlap does not check that a number or a frequency means the same thing.
The faithfulness extractor still misses claims that have no number, name,
date, or quote.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.faithfulness import check_faithfulness
from src.guards import GUARD_REDIRECT, IDENTITY_REPLY, MISSING_DETAIL

# Recalibrated in BENBOT-15 on the passages in tests/test_verify.py.
# Windowed good sentences score at least 0.875. Invented sentences the word
# list does not already catch score at most 0.50 ("recently started keeping
# bees", "AI-first as a mindset"). 0.55 sits in that gap. The merged Mindsize
# sentence scores 0.421 against one knowledge sentence and 0.947 in a window.
SUPPORT_THRESHOLD = 0.55

# Separates facts-file text from each retrieved or stuffed entry.
ENTRY_BREAK = "\f"

_HEADING = re.compile(r"^#{1,6}\s+\S")

# Flagged only when the same word or phrase is absent from the knowledge text.
CHARACTERIZATION_WORDS = (
    "collaborative",
    "supportive",
    "passionate",
    "dedicated",
    "committed",
    "driven",
    "laid-back",
    "easygoing",
    "grateful",
    "thankful",
    "excited",
    "thrilled",
    "usually",
    "often",
    "always",
    "typically",
    "generally",
    "sweet spot",
    "thrive",
    "succeed",
    "recently",
    "lately",
    "a few",
    "several",
    "many",
    "most of",
    "for a while",
    "sometimes",
)

_EXEMPT = frozenset({MISSING_DETAIL, GUARD_REDIRECT, IDENTITY_REPLY})

_WORD = re.compile(r"[a-z0-9']+")
_STOP = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "if",
        "when",
        "while",
        "because",
        "as",
        "at",
        "by",
        "for",
        "from",
        "in",
        "into",
        "of",
        "on",
        "to",
        "with",
        "without",
        "about",
        "after",
        "before",
        "during",
        "than",
        "then",
        "that",
        "this",
        "these",
        "those",
        "it",
        "its",
        "my",
        "your",
        "our",
        "their",
        "his",
        "her",
        "he",
        "she",
        "we",
        "you",
        "they",
        "me",
        "him",
        "them",
        "us",
        "what",
        "which",
        "who",
        "whom",
        "whose",
        "where",
        "why",
        "how",
        "yes",
        "no",
        "not",
        "do",
        "does",
        "did",
        "done",
        "be",
        "am",
        "is",
        "are",
        "was",
        "were",
        "been",
        "being",
        "have",
        "has",
        "had",
        "having",
        "can",
        "could",
        "would",
        "should",
        "may",
        "might",
        "must",
        "will",
        "shall",
        "also",
        "just",
        "only",
        "even",
        "still",
        "already",
        "here",
        "there",
        "so",
        "very",
        "more",
        "most",
        "some",
        "any",
        "all",
        "each",
        "every",
        "both",
        "few",
        "other",
        "another",
        "such",
        "same",
        "own",
        "i",
        "i'm",
        "i've",
        "i'd",
        "don't",
        "doesn't",
        "didn't",
        "it's",
        "that's",
        "we're",
        "they're",
        "you're",
        "i'll",
        "can't",
        "won't",
    }
)


@dataclass(frozen=True)
class SentenceScore:
    text: str
    score: float
    unsupported: bool


@dataclass
class Verification:
    ok: bool
    sentence_scores: list[SentenceScore] = field(default_factory=list)
    unsupported_characterizations: list[str] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)

    def flagged_sentences(self) -> list[str]:
        return [row.text for row in self.sentence_scores if row.unsupported]

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "threshold": SUPPORT_THRESHOLD,
            "flagged_sentences": self.flagged_sentences(),
            "sentence_scores": [
                {"text": row.text, "score": round(row.score, 4), "unsupported": row.unsupported}
                for row in self.sentence_scores
            ],
            "unsupported_characterizations": list(self.unsupported_characterizations),
            "unsupported_claims": list(self.unsupported_claims),
        }


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"[\n.!?]+", text)
    return [part.strip(" \t-") for part in parts if part.strip(" \t-")]


def _stem(word: str) -> str:
    for suffix, min_stem in (("ing", 4), ("ed", 4), ("ly", 4), ("es", 4), ("s", 4)):
        if word.endswith(suffix) and len(word) - len(suffix) >= min_stem:
            if suffix == "s" and word.endswith("ss"):
                continue
            return word[: -len(suffix)]
    return word


def content_words(text: str) -> list[str]:
    """Lowercase content words with light suffix stripping and stopwords removed."""
    words: list[str] = []
    for raw in _WORD.findall(text.lower()):
        if raw in _STOP:
            continue
        stemmed = _stem(raw)
        if stemmed in _STOP or len(stemmed) < 3:
            continue
        words.append(stemmed)
    return words


def support_score_single(sentence: str, knowledge: str) -> float:
    """BENBOT-13 score: best overlap with one knowledge sentence, no windows."""
    return _best_overlap(sentence, split_sentences(knowledge))


def support_score(sentence: str, knowledge: str) -> float:
    """Share of content words found in the best knowledge window.

    Windows are 1, 2, or 3 consecutive sentences inside one segment.
    A sentence with no content words scores 1.0 (nothing to contradict).
    """
    words = content_words(sentence)
    if not words:
        return 1.0
    best = 0.0
    for group in knowledge_sentence_groups(knowledge):
        best = max(best, _best_overlap(sentence, _windows(group)))
    return best


def knowledge_sentence_groups(knowledge: str) -> list[list[str]]:
    """Sentences grouped so a window cannot cross an entry or a heading."""
    groups: list[list[str]] = []
    for unit in knowledge.split(ENTRY_BREAK):
        groups.extend(_sections(unit))
    return groups


def prune_flagged_sentences(text: str, flagged: list[str]) -> str:
    """Delete only the flagged sentences. Keep the others, in order.

    The result is empty when every sentence was flagged. Each kept sentence
    ends with punctuation so the reply does not start mid-sentence.
    """
    banned = {item.strip() for item in flagged}
    kept: list[str] = []
    for piece in answer_sentences(text):
        keys = split_sentences(piece)
        if keys and keys[0] in banned:
            continue
        kept.append(piece if piece[-1:] in ".!?" else piece + ".")
    return " ".join(kept)


def starts_complete(text: str) -> bool:
    """True when the reply starts a sentence rather than a leftover fragment."""
    stripped = text.strip()
    if not stripped:
        return False
    return stripped[0].isupper()


def minimum_kept(original_count: int, configured: int) -> int:
    """How many sentences a prune must keep.

    A short draft may keep a single sentence. A longer draft must keep the
    configured minimum (VERIFY_PRUNE_MIN_SENTENCES, default 2).
    """
    if original_count <= configured:
        return 1
    return max(configured, 1)


def unsupported_characterizations(text: str, knowledge: str) -> list[str]:
    """Listed words present in the answer and absent from the knowledge."""
    found: list[str] = []
    for word in CHARACTERIZATION_WORDS:
        if _has_word(text, word) and not _has_word(knowledge, word):
            found.append(word)
    return found


def verify_answer(answer: str, knowledge: str) -> Verification:
    """Run faithfulness, characterization, and sentence-support checks."""
    stripped = answer.strip()
    if stripped in _EXEMPT:
        return Verification(ok=True, sentence_scores=[SentenceScore(stripped, 1.0, False)])
    # Nothing was sent to compare against, so the checks have no evidence.
    if not knowledge.strip():
        return Verification(ok=True, sentence_scores=[SentenceScore(stripped, 1.0, False)])

    claims = check_faithfulness(stripped, knowledge)
    claim_texts = [token.text for token in claims.unsupported]
    characterizations = unsupported_characterizations(stripped, knowledge)
    char_pattern = _characterization_pattern(characterizations)

    scores: list[SentenceScore] = []
    for sentence in split_sentences(stripped) or [stripped]:
        score = support_score(sentence, knowledge)
        low = score < SUPPORT_THRESHOLD
        has_char = bool(char_pattern and char_pattern.search(sentence))
        has_claim = any(_has_word(sentence, claim) for claim in claim_texts)
        scores.append(SentenceScore(sentence, score, low or has_char or has_claim))

    ok = not claim_texts and not characterizations and all(not row.unsupported for row in scores)
    return Verification(
        ok=ok,
        sentence_scores=scores,
        unsupported_characterizations=characterizations,
        unsupported_claims=claim_texts,
    )


def corrective_note(verdict: Verification) -> str:
    """Note appended to the user message so a temperature-0 retry is a new input."""
    named = verdict.flagged_sentences()
    if not named:
        named = ["(the previous answer)"]
    quoted = " | ".join(named)
    return (
        "Rewrite the answer. Keep every supported sentence unchanged. "
        "Rewrite or remove only the flagged sentences. "
        "Do not drop supported facts. "
        "Add no traits, frequencies, or comparisons. "
        f"These sentences are unsupported: {quoted}"
    )


def answer_sentences(text: str) -> list[str]:
    """Sentences in order, with their terminating punctuation."""
    sentences: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        parts = re.split(r"([.!?]+)", line)
        index = 0
        while index < len(parts):
            body = parts[index].strip(" \t-")
            punct = ""
            if index + 1 < len(parts) and re.fullmatch(r"[.!?]+", parts[index + 1]):
                punct = parts[index + 1]
                index += 2
            else:
                index += 1
            if body:
                sentences.append(body + punct)
    return sentences


def _sections(unit: str) -> list[list[str]]:
    groups: list[list[str]] = []
    lines: list[str] = []

    def flush() -> None:
        text = "\n".join(lines).strip()
        lines.clear()
        sentences = split_sentences(text) if text else []
        if sentences:
            groups.append(sentences)

    for line in unit.splitlines():
        if _HEADING.match(line.strip()):
            flush()
            continue
        lines.append(line)
    flush()
    return groups


def _windows(sentences: list[str]) -> list[str]:
    spans: list[str] = []
    for width in (1, 2, 3):
        if len(sentences) < width:
            continue
        for start in range(len(sentences) - width + 1):
            spans.append(" ".join(sentences[start : start + width]))
    return spans


def _best_overlap(sentence: str, spans: list[str]) -> float:
    words = content_words(sentence)
    if not words:
        return 1.0
    best = 0.0
    for span in spans:
        known = set(content_words(span))
        if not known:
            continue
        hits = sum(1 for word in words if word in known)
        best = max(best, hits / len(words))
    return best


def _has_word(haystack: str, word: str) -> bool:
    return (
        re.search(rf"(?i)(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", haystack) is not None
    )


def _characterization_pattern(words: list[str]) -> re.Pattern[str] | None:
    if not words:
        return None
    body = "|".join(re.escape(word) for word in words)
    return re.compile(rf"(?i)(?<![A-Za-z])(?:{body})(?![A-Za-z])")
