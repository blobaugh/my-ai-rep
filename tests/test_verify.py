"""Sentence support, characterization, and the calibration gap."""

from src.verify import (
    ENTRY_BREAK,
    SUPPORT_THRESHOLD,
    corrective_note,
    minimum_kept,
    prune_flagged_sentences,
    support_score,
    unsupported_characterizations,
    verify_answer,
)

# Passages that justify the good sentences. They do not contain the invented
# traits in the bad sentences.
KNOWLEDGE = """
I lead as a servant leader: my job is to help pave the way for my team's success. I don't micromanage. I trust the team to accomplish their work. I step in and work closely with someone when it's needed or when they're struggling.
I have run weekly coaching sessions at Northwind Studio since June 2019.
I want a remote coaching practice, ideally one that involves some work with written playbooks.
I keep a small reading list.
"""

BAD = [
    "It's about creating an environment where my team can thrive and succeed.",
    "I'm committed to creating a supportive and collaborative work environment.",
    "I've been known to get a little competitive in reviews.",
    "I've got a sweet spot for tidy backlogs.",
    "I've recently started writing playbooks.",
    "We often go on working sessions and writing days.",
]

GOOD = [
    "I lead as a servant leader, which means my job is to help pave the way for my team's success.",
    "I don't micromanage, instead I trust the team to do their work and step in when needed or when they're struggling.",
    "I have run weekly coaching sessions at Northwind Studio since June 2019.",
    "I want a remote coaching practice, ideally one that involves some work with written playbooks.",
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


def test_fixed_lines_are_exempt_only_when_passed() -> None:
    from src.guards import persona_lines

    line = persona_lines("Ada", "Bot").missing
    assert verify_answer(line, KNOWLEDGE, exempt=frozenset({line})).ok is True
    assert verify_answer(line, KNOWLEDGE).ok is False


def test_characterization_flags_only_words_absent_from_knowledge() -> None:
    assert unsupported_characterizations("I often sail.", "I often sail on Saturdays.") == []
    assert "recently" in unsupported_characterizations(
        "I recently started.", "I keep bees."
    )


def test_overlap_cannot_tell_often_from_a_similar_sentence() -> None:
    """'often' is already in this entry, and the other words match it.

    The support check cannot see that 'often' replaced 'a lot'.
    """
    knowledge = (
        "I don't get to the studio as often now, "
        "but we go on a lot of working sessions and writing days."
    )
    sentence = "We often go on working sessions and writing days."
    assert support_score(sentence, knowledge) >= SUPPORT_THRESHOLD
    assert verify_answer(sentence, knowledge).ok is True


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


def test_prune_deletes_only_flagged_sentences() -> None:
    draft = (
        "I have run weekly coaching sessions at Northwind Studio since June 2019. "
        "I've got a sweet spot for tidy backlogs. "
        "I write short playbooks for backlog hygiene."
    )
    flagged = ["I've got a sweet spot for tidy backlogs"]
    pruned = prune_flagged_sentences(draft, flagged)
    assert pruned.startswith("I have run weekly")
    assert "sweet spot" not in pruned
    assert "playbooks" in pruned
    assert minimum_kept(3, 2) == 2
    assert minimum_kept(2, 2) == 1


def test_corrective_note_keeps_supported_sentences() -> None:
    verdict = verify_answer(BAD[0], KNOWLEDGE)
    note = corrective_note(verdict)
    assert "Keep every supported sentence unchanged." in note
    assert "Rewrite or remove only the flagged sentences." in note
    assert "Do not drop supported facts." in note
    assert "Add no traits, frequencies, or comparisons." in note
