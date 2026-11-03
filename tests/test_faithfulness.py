"""Unit tests for faithfulness and recitation checks."""

from __future__ import annotations

from src.faithfulness import check_faithfulness, recitation_score


def test_unsupported_number_flagged() -> None:
    grounding = "I grew the practice from 2 to 8 coaches."
    result = check_faithfulness("I grew the practice to 99 coaches.", grounding)
    texts = {t.text for t in result.unsupported}
    assert "99" in texts


def test_supported_number_and_spelled_out_pass() -> None:
    grounding = "I grew the practice from 2 to 8. The notes went from one page to five."
    result = check_faithfulness(
        "I grew the practice to 8 and the notes to five pages.",
        grounding,
    )
    assert result.unsupported == []


def test_sentence_initial_capital_not_flagged() -> None:
    grounding = "I work with leaders on coaching."
    result = check_faithfulness(
        "Working with leaders is what I do most days.",
        grounding,
    )
    kinds = {t.kind for t in result.unsupported}
    assert "title" not in kinds or all(
        t.text != "Working" for t in result.unsupported
    )


def test_invented_name_flagged() -> None:
    grounding = "I worked at Northwind Studio as a product coach."
    result = check_faithfulness(
        "I worked at AcmeCorp with Jane Doe on projects.",
        grounding,
    )
    texts = {t.text for t in result.unsupported}
    assert "AcmeCorp" in texts or "Jane Doe" in texts


def test_recitation_unrelated_is_zero() -> None:
    score = recitation_score(
        "The quick brown fox jumps over the lazy dog today.",
        "Completely different source material about written playbooks.",
    )
    assert score == 0.0


def test_recitation_verbatim_near_one() -> None:
    source = (
        "I believe in servant leadership and paving the way for the team's success "
        "with regular mentoring and clear standards."
    )
    score = recitation_score(source, source)
    assert score > 0.9
