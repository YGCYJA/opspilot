from pathlib import Path

import pytest

from opspilot.retrieval import ingest, Retriever


def test_changed_rules_have_new_citation_ids_and_source_lines(tmp_path):
    note = tmp_path / 'rules.md'
    note.write_text('# Discount\nThreshold is inclusive: subtotal >= 100.\n')
    original = ingest(tmp_path)
    assert original[0].line_start == 2
    note.write_text('# Discount\nThreshold is exclusive: subtotal > 100.\n')
    assert ingest(tmp_path)[0].id != original[0].id
    assert Retriever(ingest(tmp_path)).search('discount threshold', k=1, method='bm25')[0]['doc_id'] == 'rules.md'


def test_empty_notes_do_not_fabricate_a_match():
    assert Retriever([]).search('discount', method='bm25') == []


def test_bounded_chunks_and_invalid_search_limits(tmp_path):
    (tmp_path / 'rules.md').write_text('# Heading\n' + 'x' * 2000)
    assert all(len(c.text) <= 480 for c in ingest(tmp_path))
    with pytest.raises(ValueError):
        Retriever([]).search('discount', k=0)
