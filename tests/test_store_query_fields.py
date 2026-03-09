"""Tests for store query fields."""

from __future__ import annotations

from memsearch.store import MilvusStore


class TestStoreQueryFields:
    def test_query_fields_defined(self):
        """_QUERY_FIELDS should be defined."""
        assert hasattr(MilvusStore, '_QUERY_FIELDS')

    def test_query_fields_is_list(self):
        """_QUERY_FIELDS should be a list."""
        assert isinstance(MilvusStore._QUERY_FIELDS, list)

    def test_query_fields_not_empty(self):
        """_QUERY_FIELDS should not be empty."""
        assert len(MilvusStore._QUERY_FIELDS) > 0

    def test_query_fields_contains_content(self):
        """_QUERY_FIELDS should include content field."""
        assert "content" in MilvusStore._QUERY_FIELDS

    def test_query_fields_contains_source(self):
        """_QUERY_FIELDS should include source field."""
        assert "source" in MilvusStore._QUERY_FIELDS

    def test_query_fields_contains_heading(self):
        """_QUERY_FIELDS should include heading field."""
        assert "heading" in MilvusStore._QUERY_FIELDS

    def test_query_fields_contains_chunk_hash(self):
        """_QUERY_FIELDS should include chunk_hash field."""
        assert "chunk_hash" in MilvusStore._QUERY_FIELDS

    def test_query_fields_contains_metadata(self):
        """_QUERY_FIELDS should include metadata fields."""
        fields = MilvusStore._QUERY_FIELDS
        assert "heading_level" in fields
        assert "start_line" in fields
        assert "end_line" in fields