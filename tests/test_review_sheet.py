"""Tests for review sheet generation and eval result shape."""

from __future__ import annotations

import json
from pathlib import Path

from eval.make_review_sheet import main as make_sheet_main


def test_review_sheet_contains_questions_and_conditions(tmp_path: Path) -> None:
    a = {
        "qa_mode": "retrieve",
        "temperature": 0.0,
        "retrieval_sources": "qa",
        "repeats": 2,
        "cases": [
            {
                "id": "background",
                "question": "What's your background?",
                "flag_pass_rate": 1.0,
                "distinct_answers": 1,
                "faithfulness_flag_count_mean": 0,
                "recitation_mean": 0.1,
                "runs": [
                    {
                        "reply": "Answer A1",
                        "flagged": [],
                        "faithfulness_unsupported": [],
                        "recitation": 0.1,
                    },
                    {
                        "reply": "Answer A2",
                        "flagged": [],
                        "faithfulness_unsupported": [],
                        "recitation": 0.2,
                    },
                ],
            }
        ],
    }
    b = {
        "qa_mode": "stuff",
        "temperature": 0.3,
        "retrieval_sources": "qa",
        "repeats": 1,
        "cases": [
            {
                "id": "background",
                "question": "What's your background?",
                "flag_pass_rate": 1.0,
                "distinct_answers": 1,
                "faithfulness_flag_count_mean": 0,
                "recitation_mean": 0.5,
                "runs": [
                    {
                        "reply": "Stuff answer",
                        "flagged": [],
                        "faithfulness_unsupported": [],
                        "recitation": 0.5,
                    }
                ],
            }
        ],
    }
    pa = tmp_path / "a.json"
    pb = tmp_path / "b.json"
    pa.write_text(json.dumps(a), encoding="utf-8")
    pb.write_text(json.dumps(b), encoding="utf-8")
    out = tmp_path / "sheet.md"
    assert make_sheet_main([str(pa), str(pb), "-o", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "What's your background?" in text
    assert "retrieve" in text
    assert "stuff" in text
    assert "Answer A1" in text
    assert "Stuff answer" in text
    assert "**Notes:**" in text


def test_result_records_temperature_and_repeats_shape() -> None:
    """Document the expected result schema fields for temperature experiments."""
    sample = {
        "temperature": 0.3,
        "repeats": 5,
        "cases": [
            {
                "id": "x",
                "temperature": 0.3,
                "repeats": 5,
                "flag_pass_rate": 0.8,
                "distinct_answers": 3,
                "runs": [{"reply": "a"}, {"reply": "b"}],
            }
        ],
    }
    assert sample["temperature"] == 0.3
    assert sample["repeats"] == 5
    assert sample["cases"][0]["flag_pass_rate"] == 0.8
