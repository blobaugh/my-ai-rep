"""Sentence count and unsupported-characterization checks."""

from eval.properties import min_sentences, no_unsupported_characterization


def test_min_sentences_splits_on_punctuation() -> None:
    assert min_sentences("One fact.", 2).ok is False
    assert min_sentences("I lead. I teach.", 2).ok is True


def test_characterization_ignores_words_present_in_knowledge() -> None:
    result = no_unsupported_characterization(
        "I am usually on the water.",
        "I usually sail on Saturdays.",
    )
    assert result.ok is True


def test_characterization_flags_a_word_the_knowledge_does_not_state() -> None:
    result = no_unsupported_characterization(
        "It's a collaborative and supportive environment.",
        "I lead as a servant leader.",
    )
    assert result.ok is False
    assert result.detail is not None
    assert "collaborative" in result.detail
    assert "supportive" in result.detail


def test_characterization_flags_the_added_words() -> None:
    result = no_unsupported_characterization(
        "I recently found a sweet spot and I thrive.",
        "I keep bees.",
    )
    assert result.ok is False
    assert result.detail is not None
    assert "recently" in result.detail
    assert "sweet spot" in result.detail
    assert "thrive" in result.detail
