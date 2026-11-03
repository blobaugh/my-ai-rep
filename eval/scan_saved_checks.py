"""Run the new checks over every saved result file under data/eval/.

min_sentences uses a threshold of 2. A one-sentence fixed line is reported as
a false positive of that blanket threshold. Characterization uses knowledge_text
when the file stored it, plus the current facts file. Files with no knowledge
text are counted separately and are not treated as proof the word was invented.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eval.properties import (
    CHARACTERIZATION_WORDS,
    FIXED_LINES,
    _has_word,
    min_sentences,
    no_unsupported_characterization,
)

RESULTS = Path("data/eval")
ABOUT = Path("content/about-ben.md")
QA = Path("content/qa.md")


def _walk(node: Any, found: list[dict[str, Any]]) -> None:
    if isinstance(node, dict):
        reply = node.get("reply")
        if isinstance(reply, str) and reply.strip():
            knowledge = node.get("knowledge_text")
            debug = node.get("debug")
            if not isinstance(knowledge, str) and isinstance(debug, dict):
                knowledge = debug.get("knowledge_text")
            found.append(
                {
                    "reply": reply,
                    "knowledge": knowledge if isinstance(knowledge, str) else "",
                    "had_knowledge": isinstance(knowledge, str),
                }
            )
        for value in node.values():
            _walk(value, found)
    elif isinstance(node, list):
        for value in node:
            _walk(value, found)


def main() -> int:
    about = ABOUT.read_text(encoding="utf-8")
    corpus = about + "\n" + QA.read_text(encoding="utf-8")
    fixed = set(FIXED_LINES.values())
    sentence_false = 0
    sentence_other_samples: list[str] = []
    sentence_other = 0
    char_hits: list[str] = []
    corpus_overlap: list[str] = []
    missing_knowledge = 0
    replies = 0
    for path in sorted(RESULTS.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"skip unreadable {path.name}")
            continue
        rows: list[dict[str, Any]] = []
        _walk(payload, rows)
        for row in rows:
            replies += 1
            reply = str(row["reply"])
            counted = min_sentences(reply, 2)
            if not counted.ok:
                if reply.strip() in fixed:
                    sentence_false += 1
                else:
                    sentence_other += 1
                    if len(sentence_other_samples) < 8:
                        sentence_other_samples.append(reply[:160].replace("\n", " "))
            words = [word for word in CHARACTERIZATION_WORDS if _has_word(reply, word)]
            if not words:
                continue
            if not row["had_knowledge"]:
                missing_knowledge += 1
                unsupported = [word for word in words if not _has_word(corpus, word)]
                supported = [word for word in words if _has_word(corpus, word)]
                if unsupported:
                    char_hits.append(
                        f"{path.name}: not in facts or Q&A {unsupported} :: {reply[:160]}"
                    )
                if supported:
                    corpus_overlap.append(
                        f"{path.name}: word is in the corpus, sent text was not stored {supported} :: {reply[:120]}"
                    )
                continue
            flagged = no_unsupported_characterization(reply, about + "\n" + str(row["knowledge"]))
            if not flagged.ok:
                char_hits.append(f"{path.name}: {flagged.detail} :: {reply[:180]}")
    print(f"replies={replies}")
    print(f"min_sentences<2 on an exact fixed line={sentence_false}")
    print(f"min_sentences<2 on other replies={sentence_other}")
    for sample in sentence_other_samples:
        print(f"  short: {sample}")
    print(f"characterization words absent from facts and Q&A={len(char_hits)}")
    for line in char_hits[:40]:
        print(line)
    print(f"characterization words that do appear in facts or Q&A (sent text was not stored)={len(corpus_overlap)}")
    for line in corpus_overlap[:20]:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
