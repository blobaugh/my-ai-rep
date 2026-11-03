"""Sentence support, characterization, and the calibration gap."""

from pathlib import Path

import pytest

from src.qa import parse_qa
from src.verify import (
    ENTRY_BREAK,
    SUPPORT_THRESHOLD,
    corrective_note,
    minimum_kept,
    prune_flagged_sentences,
    support_score,
    support_score_single,
    unsupported_characterizations,
    verify_answer,
)

# Passages that justify the good sentences. They do not contain the invented
# traits in the bad sentences.
KNOWLEDGE = """
I lead as a servant leader: my job is to help pave the way for my team's success. I don't micromanage. I trust the team to accomplish their work. I step in and work closely with someone when it's needed or when they're struggling.
I was Director of Engineering at Mindsize from June 2019 to September 2026.
I want an executive-level position, director and up, ideally one that involves some work with AI.
I'm a sailor and a beekeeper.
"""

BAD = [
    "It's about creating an environment where my team can thrive and succeed.",
    "I'm committed to creating a supportive and collaborative work environment.",
    "I've been known to get a little competitive on the water.",
    "I've got a sweet spot for my bees.",
    "I've recently started keeping bees.",
    "We often go on family cruises and day sails.",
]

GOOD = [
    "I lead as a servant leader, which means my job is to help pave the way for my team's success.",
    "I don't micromanage, instead I trust the team to do their work and step in when needed or when they're struggling.",
    "I was Director of Engineering at Mindsize from June 2019 to September 2026.",
    "I want an executive-level position, director and up, ideally one that involves some work with AI.",
]


def test_calibration_bad_sentences_are_flagged() -> None:
    for sentence in BAD:
        verdict = verify_answer(sentence, KNOWLEDGE)
        assert verdict.ok is False, sentence
        assert verdict.flagged_sentences(), sentence


def test_calibration_good_sentences_pass() -> None:
    scores = [support_score(sentence, KNOWLEDGE) for sentence in GOOD]
    assert min(scores) >= SUPPORT_THRESHOLD
    for sentence in GOOD:
        verdict = verify_answer(sentence, KNOWLEDGE)
        assert verdict.ok is True, (sentence, verdict.as_dict())


def test_bad_support_scores_sit_below_the_threshold() -> None:
    scores = [support_score(sentence, KNOWLEDGE) for sentence in BAD]
    assert max(scores) < SUPPORT_THRESHOLD


def test_fixed_lines_are_exempt() -> None:
    line = "I don't have that detail. You can ask the real Ben directly."
    assert verify_answer(line, KNOWLEDGE).ok is True


def test_characterization_flags_only_words_absent_from_knowledge() -> None:
    assert unsupported_characterizations("I often sail.", "I often sail on Saturdays.") == []
    assert "recently" in unsupported_characterizations(
        "I recently started.", "I keep bees."
    )


def test_overlap_cannot_tell_often_from_the_real_cruise_sentence() -> None:
    """'often' is already in this entry, and the other words match it.

    The support check cannot see that 'often' replaced 'a lot'.
    """
    knowledge = (
        "With three young kids I don't get to race as often now, "
        "but we go on a lot of family cruises and day sails."
    )
    sentence = "We often go on family cruises and day sails."
    assert support_score(sentence, knowledge) >= SUPPORT_THRESHOLD
    assert verify_answer(sentence, knowledge).ok is True


MERGED_MINDSIZE = (
    "During my time there, I grew the engineering team from 2 to 15 engineers, "
    "extended average engineer retention from 1 year to 5 years, and built the "
    "software development lifecycle, a mentorship program, and a hiring program."
)

# Saved eval answers, checked against the entry named in the comment.
MORE_GOOD = [
    (
        "intro",
        (
            "I'm a leadership development consultant with a career in technology, "
            "mostly web development."
        ),
    ),
    (
        "intro",
        "I've worked with WordPress, Laravel, and custom Node-based ecommerce.",
    ),
    ("management-style", "I don't micromanage."),
    ("ideal-role", "What I want most is to lead people."),
    (
        "ideal-role",
        (
            "The role needs to be remote, with some travel being fine, because I "
            "want to be home with my family most of the time."
        ),
    ),
    (
        "ideal-role",
        "Flexible hours matter to me, and a set of company core hours is fine.",
    ),
    ("sailing-love", "I love the serenity of being out on the water."),
    ("sailing-love", "It's calming and intensely relaxing."),
    (
        "sailing-love",
        (
            "With three young kids I don't get to race as often now, but we go on "
            "a lot of family cruises and day sails."
        ),
    ),
    (
        "about-ben Interests",
        "I'm a competitive sailor and an award-winning skipper.",
    ),
    (
        "about-ben Current and recent work",
        "My team spanned the USA, Canada, and the Philippines.",
    ),
    (
        "about-ben Current and recent work",
        "I was Director of Engineering at Mindsize from June 2019 to September 2026.",
    ),
]


def _require_private_content(*names: str) -> None:
    missing = [name for name in names if not Path(name).is_file()]
    if missing:
        pytest.skip("private content not present: " + ", ".join(missing))


def _full_knowledge() -> str:
    _require_private_content("content/about-ben.md", "content/qa.md")
    facts = Path("content/about-ben.md").read_text(encoding="utf-8")
    entries = parse_qa(Path("content/qa.md").read_text(encoding="utf-8"))
    parts = [facts.strip()] + [entry.answer.strip() for entry in entries]
    return ENTRY_BREAK.join(parts)


def test_window_keeps_the_merged_mindsize_sentence() -> None:
    _require_private_content("content/about-ben.md")
    facts = Path("content/about-ben.md").read_text(encoding="utf-8")
    old = support_score_single(MERGED_MINDSIZE, facts)
    new = support_score(MERGED_MINDSIZE, facts)
    assert old < SUPPORT_THRESHOLD
    assert new >= SUPPORT_THRESHOLD
    assert verify_answer(MERGED_MINDSIZE, facts).ok is True


def test_windows_do_not_cross_headings_or_entries() -> None:
    headings = (
        "## garden\n"
        "I grow tomatoes in the garden every summer.\n"
        "## water\n"
        "I race sailboats on Puget Sound.\n"
    )
    entries = ENTRY_BREAK.join(
        [
            "I grow tomatoes in the garden every summer.",
            "I race sailboats on Puget Sound.",
        ]
    )
    sentence = "I grow tomatoes in the garden and race sailboats on Puget Sound."
    crossed = (
        "I grow tomatoes in the garden every summer. "
        "I race sailboats on Puget Sound."
    )
    assert support_score(sentence, crossed) == 1.0
    assert support_score(sentence, headings) < 0.8
    assert support_score(sentence, entries) < 0.8


def test_saved_good_sentences_pass_and_bad_ones_stay_flagged() -> None:
    knowledge = _full_knowledge()
    for _entry, sentence in MORE_GOOD:
        verdict = verify_answer(sentence, knowledge)
        assert verdict.ok is True, (sentence, verdict.as_dict())
    assert verify_answer(MERGED_MINDSIZE, knowledge).ok is True
    limited = "We often go on family cruises and day sails."
    assert verify_answer(limited, knowledge).ok is True
    must_flag = [sentence for sentence in BAD if sentence != limited]
    must_flag.extend(
        [
            (
                "It's a collaborative and supportive environment, where I'm there to "
                "help my team members grow and succeed."
            ),
            "I've been sailing for a while now.",
            "I think of AI-first as a mindset, not just a technology.",
            (
                "It's about recognizing the potential of AI to augment and amplify "
                "human capabilities, rather than replacing them."
            ),
        ]
    )
    for sentence in must_flag:
        verdict = verify_answer(sentence, knowledge)
        assert verdict.ok is False, (sentence, verdict.as_dict())


def test_prune_deletes_only_flagged_sentences() -> None:
    draft = (
        "I was Director of Engineering at Mindsize from June 2019 to September 2026. "
        "I've got a sweet spot for my bees. "
        "My team spanned the USA, Canada, and the Philippines."
    )
    flagged = ["I've got a sweet spot for my bees"]
    pruned = prune_flagged_sentences(draft, flagged)
    assert pruned.startswith("I was Director")
    assert "sweet spot" not in pruned
    assert "Philippines" in pruned
    assert minimum_kept(3, 2) == 2
    assert minimum_kept(2, 2) == 1


def test_corrective_note_keeps_supported_sentences() -> None:
    verdict = verify_answer(BAD[0], KNOWLEDGE)
    note = corrective_note(verdict)
    assert "Keep every supported sentence unchanged." in note
    assert "Rewrite or remove only the flagged sentences." in note
    assert "Do not drop supported facts." in note
    assert "Add no traits, frequencies, or comparisons." in note
