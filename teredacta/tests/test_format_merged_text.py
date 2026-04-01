"""Regression tests for format_merged_text, especially table markup handling.

The _TABLE_RE regex previously caused catastrophic backtracking on unclosed
table markup (recovery 49124). The fix replaced it with string-based matching.
"""

import signal
import pytest
from teredacta.unob import UnobInterface


class TestTableMarkup:
    """Table restoration in format_merged_text."""

    def test_well_formed_table_restored(self):
        text = "<table><tr><td>cell 1</td><td>cell 2</td></tr></table>"
        result = UnobInterface.format_merged_text(text)
        assert '<table class="data-table"' in result
        assert "<tr>" in result
        assert "<td>cell 1</td>" in result

    def test_table_with_th_restored(self):
        text = "<table><tr><th>Header</th></tr><tr><td>Data</td></tr></table>"
        result = UnobInterface.format_merged_text(text)
        assert "<th>Header</th>" in result
        assert "<td>Data</td>" in result

    def test_unclosed_table_does_not_hang(self):
        """Regression test for recovery 49124: unclosed table must not hang."""
        # Simulate the pathological pattern: <table> with rows but no </table>
        text = (
            "<table><tr><td>row 1</td></tr>"
            "<tr><td>row 2</td></tr>"
            "<tr><td>" + "x" * 1500  # No closing tags
        )

        def _timeout_handler(signum, frame):
            raise TimeoutError("format_merged_text hung on unclosed table")

        old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(3)
        try:
            result = UnobInterface.format_merged_text(text)
            # Should complete and return escaped text (table not restored)
            assert "row 1" in result
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)

    def test_unclosed_table_not_restored(self):
        """Unclosed table markup should be left as escaped HTML."""
        text = "<table><tr><td>data</td></tr>"  # No </table>
        result = UnobInterface.format_merged_text(text)
        # Table tags should remain escaped since there's no closing tag
        assert '<table class="data-table"' not in result
        assert "&lt;table&gt;" in result

    def test_multiple_tables(self):
        text = (
            "Before <table><tr><td>A</td></tr></table>"
            " middle "
            "<table><tr><td>B</td></tr></table> after"
        )
        result = UnobInterface.format_merged_text(text)
        assert result.count('<table class="data-table"') == 2
        assert "<td>A</td>" in result
        assert "<td>B</td>" in result
        assert "Before" in result
        assert "middle" in result
        assert "after" in result

    def test_no_table_markup_unchanged(self):
        text = "Just plain text with no tables."
        result = UnobInterface.format_merged_text(text)
        assert result == "Just plain text with no tables."

    def test_table_without_row_tags_not_restored(self):
        """A <table></table> with no tr/th/td should not be converted."""
        text = "<table>just text</table>"
        result = UnobInterface.format_merged_text(text)
        assert '<table class="data-table"' not in result


class TestChangeMarkup:
    """Recovered text markup handling."""

    def test_change_u_converted_to_mark(self):
        text = "normal <change><u>recovered</u></change> text"
        result = UnobInterface.format_merged_text(text)
        assert '<mark class="recovered-inline"' in result
        assert "recovered" in result

    def test_bare_change_tags_removed(self):
        text = "text <change>partial</change> more"
        result = UnobInterface.format_merged_text(text)
        assert "&lt;change&gt;" not in result
        assert "partial" in result

    def test_bare_u_tags_removed(self):
        text = "text <u>underline</u> more"
        result = UnobInterface.format_merged_text(text)
        assert "&lt;u&gt;" not in result
        assert "underline" in result
