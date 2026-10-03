from app.pdf_export import _plain, _task_notes, build_pdf


def test_plain_strips_markdown_and_collapses_whitespace():
    assert _plain("**Bold**  and `code`\n\n[a link](http://x.y)") == "Bold and code a link"


def test_plain_caps_length():
    assert len(_plain("word " * 400)) <= 500


def test_task_notes_labels_summary_with_status():
    notes = _task_notes({"description": "ctx", "completionSummary": "did it", "completionSummaryStatus": "done"})
    assert notes == [("Description", "ctx"), ("Execution summary (done)", "did it")]
    assert _task_notes({"text": "bare task"}) == []


def test_build_pdf_with_notes_produces_a_pdf():
    board = {"title": "B", "color": "blue", "tasks": [
        {"text": "t", "done": False, "description": "x " * 600, "completionSummary": "ok"},
    ]}
    assert build_pdf([board]).startswith(b"%PDF")
