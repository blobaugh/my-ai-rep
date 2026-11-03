"""Advisory faithfulness and recitation checks (pure; no I/O).

Limits: invented claims with no number, name, date, title, or quote cannot be
caught. Capitalization heuristics and spelled-out numbers also produce false
positives and misses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Sentence-initial / common words that look like Proper Nouns but are not.
NAME_STOPLIST = frozenset(
    {
        "i",
        "i'm",
        "i've",
        "i'd",
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
        "new",
        "old",
        "first",
        "last",
        "next",
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "eleven",
        "twelve",
        "twenty",
        "thirty",
        "forty",
        "fifty",
        "sixty",
        "seventy",
        "eighty",
        "ninety",
        "hundred",
        "thousand",
        "million",
        "billion",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "january",
        "february",
        "march",
        "april",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
        "director",
        "engineering",
        "team",
        "people",
        "work",
        "role",
        "job",
        "company",
        "business",
        "leader",
        "leaders",
        "leadership",
        "coach",
        "coaching",
        "mentor",
        "mentoring",
        "remote",
        "ai",
        "bot",
    }
)

SPELLED_NUMBERS = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
    "thirteen": "13",
    "fourteen": "14",
    "fifteen": "15",
    "sixteen": "16",
    "seventeen": "17",
    "eighteen": "18",
    "nineteen": "19",
    "twenty": "20",
    "thirty": "30",
    "forty": "40",
    "fifty": "50",
    "sixty": "60",
    "seventy": "70",
    "eighty": "80",
    "ninety": "90",
    "hundred": "100",
    "thousand": "1000",
    "million": "1000000",
}

DIGIT_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?%?\b")
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
DATE_RE = re.compile(
    r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s+\d{4})\b",
    re.IGNORECASE,
)
# Double quotes only — apostrophes in contractions (I'm) are not quote delimiters.
QUOTED_RE = re.compile(r'"([^"]{2,80})"')
# Multi-word Title Case / CapWords sequences (not sentence-initial handled later).
NAME_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")
SINGLE_CAP_RE = re.compile(r"\b([A-Z][a-z]{2,})\b")
WORD_RE = re.compile(r"[A-Za-z0-9']+")


@dataclass(frozen=True)
class ClaimToken:
    """One extracted claim-like token from an answer."""

    kind: str  # number | year | date | name | title | quote
    text: str


@dataclass(frozen=True)
class FaithfulnessResult:
    """Unsupported claim tokens found in an answer."""

    unsupported: list[ClaimToken]
    checked: list[ClaimToken]


def _normalize_for_lookup(text: str) -> str:
    return " ".join(text.lower().split())


def _in_context(needle: str, context_norm: str) -> bool:
    return _normalize_for_lookup(needle) in context_norm


def _sentence_starts(text: str) -> set[int]:
    """Character offsets that begin a sentence (for skipping initial caps)."""
    starts = {0}
    for m in re.finditer(r"[.!?]\s+", text):
        starts.add(m.end())
    return starts


def name_stopwords(*names: str) -> frozenset[str]:
    """Tokens from configured names that are not invented claims."""
    words: list[str] = []
    for name in names:
        words.extend(re.findall(r"[a-z0-9']+", name.lower()))
    return frozenset(words)


def extract_claim_tokens(
    answer: str, *, extra_stopwords: frozenset[str] | None = None
) -> list[ClaimToken]:
    """Extract numbers, years, dates, names/titles, and quotes from an answer."""
    stop = NAME_STOPLIST
    if extra_stopwords:
        stop = NAME_STOPLIST | {word.lower() for word in extra_stopwords}
    tokens: list[ClaimToken] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, text: str) -> None:
        key = (kind, text.strip())
        if not key[1] or key in seen:
            return
        seen.add(key)
        tokens.append(ClaimToken(kind=kind, text=key[1]))

    for m in YEAR_RE.finditer(answer):
        add("year", m.group(0))
    for m in DATE_RE.finditer(answer):
        add("date", m.group(0))
    for m in DIGIT_RE.finditer(answer):
        raw = m.group(0)
        if YEAR_RE.fullmatch(raw):
            continue
        add("number", raw)

    for word in SPELLED_NUMBERS:
        if re.search(rf"\b{word}\b", answer, re.IGNORECASE):
            add("number", word)

    for m in QUOTED_RE.finditer(answer):
        add("quote", m.group(1))

    starts = _sentence_starts(answer)
    for m in NAME_RE.finditer(answer):
        # Skip if the first word of the multi-word name is sentence-initial alone
        # and the whole span starts a sentence — still keep multi-word names.
        add("name", m.group(1))

    for m in SINGLE_CAP_RE.finditer(answer):
        if m.start() in starts:
            continue
        # Skip if this single cap is part of an already-captured multi-word name.
        word = m.group(1)
        if word.lower() in stop:
            continue
        # Skip months already handled as dates when followed by a day — keep simple.
        add("title", word)

    return tokens


def check_faithfulness(
    answer: str,
    grounding_text: str,
    *,
    extra_stopwords: frozenset[str] | None = None,
) -> FaithfulnessResult:
    """Return claim tokens in the answer that do not appear in grounding_text.

    grounding_text should be the text actually sent to the model (system prompt
    plus retrieved / stuffed knowledge). Matching is case-insensitive substring.
    """
    context_norm = _normalize_for_lookup(grounding_text)
    checked = extract_claim_tokens(answer, extra_stopwords=extra_stopwords)
    unsupported: list[ClaimToken] = []
    for token in checked:
        if token.kind == "number" and token.text.lower() in SPELLED_NUMBERS:
            # Accept if either the word or its digit form is in context.
            digit = SPELLED_NUMBERS[token.text.lower()]
            if _in_context(token.text, context_norm) or _in_context(digit, context_norm):
                continue
            unsupported.append(token)
            continue
        if _in_context(token.text, context_norm):
            continue
        # Digits with commas: also try without commas.
        if token.kind == "number":
            stripped = token.text.replace(",", "")
            if _in_context(stripped, context_norm):
                continue
        unsupported.append(token)
    return FaithfulnessResult(unsupported=unsupported, checked=checked)


def tokenize_words(text: str) -> list[str]:
    """Lowercase word tokens for n-gram overlap."""
    return [w.lower() for w in WORD_RE.findall(text)]


def word_ngrams(words: list[str], n: int = 5) -> list[tuple[str, ...]]:
    if len(words) < n:
        return []
    return [tuple(words[i : i + n]) for i in range(len(words) - n + 1)]


def recitation_score(
    answer: str,
    source_text: str,
    *,
    n: int = 5,
) -> float:
    """Fraction of answer word n-grams that appear verbatim in source_text.

    Returns 0.0 when the answer has fewer than n words. source_text should be
    the retrieved or stuffed Q&A text (not the whole system prompt), so the
    measure reflects copying from knowledge entries.
    """
    ans_words = tokenize_words(answer)
    grams = word_ngrams(ans_words, n=n)
    if not grams:
        return 0.0
    src_set = set(word_ngrams(tokenize_words(source_text), n=n))
    if not src_set:
        return 0.0
    hits = sum(1 for g in grams if g in src_set)
    return hits / len(grams)
