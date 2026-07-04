#!/usr/bin/env python3
"""Unit tests for hooks/doc_sync/extract.py — covers all 4 defects + known-file cases."""

import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

# Ensure hooks package is importable regardless of working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hooks.doc_sync.extract import (
    _extract_json_yaml_desc,
    _extract_py_desc,
    _extract_sh_desc,
    _parse_frontmatter,
    extract_description,
)


# ---------------------------------------------------------------------------
# DEFECT 1: JSON/YAML hardcode fix + known-file lookup
# ---------------------------------------------------------------------------

class TestJsonYamlIntrospection:
    """extract_description must not return hardcoded 'json config' / 'yaml config'."""

    def test_settings_json_known_file_description(self, tmp_path):
        """settings.json returns the known-file description regardless of content."""
        f = tmp_path / 'settings.json'
        f.write_text('{}')
        result = extract_description(f)
        assert result == 'Claude Code harness configuration (permissions, hooks, env, model)'

    def test_settings_template_json_known_file_description(self, tmp_path):
        """settings.template.json returns the known-file description."""
        f = tmp_path / 'settings.template.json'
        f.write_text('{}')
        result = extract_description(f)
        assert result == 'Distributable harness settings template (uses CLAUDE_HOME placeholders)'

    def test_json_uses_title_key(self, tmp_path):
        """Generic JSON file with 'title' key returns that value, not 'json config'."""
        import json
        f = tmp_path / 'some_other.json'
        f.write_text(json.dumps({'title': 'My Tool Config', 'version': '1.0'}))
        result = extract_description(f)
        assert result == 'My Tool Config'

    def test_json_uses_name_key(self, tmp_path):
        """Generic JSON file with 'name' key (no 'title') returns the name."""
        import json
        f = tmp_path / 'package.json'
        f.write_text(json.dumps({'name': 'my-package', 'version': '1.0'}))
        result = extract_description(f)
        assert result == 'my-package'

    def test_json_key_summary_fallback(self, tmp_path):
        """JSON with no title/name/description falls back to key summary (not 'json config')."""
        import json
        f = tmp_path / 'config.json'
        f.write_text(json.dumps({'alpha': 1, 'beta': 2, 'gamma': 3}))
        result = extract_description(f)
        assert result != 'json config'
        assert 'alpha' in result or 'JSON' in result

    def test_json_malformed_graceful_fallback(self, tmp_path):
        """Malformed JSON gracefully falls back to 'json config'."""
        f = tmp_path / 'bad.json'
        f.write_text('{not valid json}')
        result = extract_description(f)
        assert result == 'json config'

    def test_yaml_uses_description_key(self, tmp_path):
        """YAML file with 'description' key returns that value."""
        f = tmp_path / 'action.yaml'
        f.write_text('name: My Action\ndescription: Deploy the application\n')
        result = extract_description(f)
        # description or name key — either is acceptable per spec
        assert result in ('Deploy the application', 'My Action')
        assert result != 'yaml config'

    def test_requirements_txt_known_file(self, tmp_path):
        """requirements.txt returns the known-file description."""
        f = tmp_path / 'requirements.txt'
        f.write_text('pytest\nrequests\n')
        result = extract_description(f)
        assert result == 'Python dependency manifest for the Claude Code harness venv'


# ---------------------------------------------------------------------------
# DEFECT 2: Shell separator fix
# ---------------------------------------------------------------------------

class TestShellSeparatorFix:
    """_extract_sh_desc must skip bare # separator lines."""

    def test_shell_skips_separator_comment(self, tmp_path):
        """push.sh-style file: first comment is # === separator, real desc follows."""
        f = tmp_path / 'push.sh'
        f.write_text(textwrap.dedent("""\
            #!/usr/bin/env bash
            #
            # push.sh - Global pre-push checks: git identity + fetch/pull/status
            #
            set -euo pipefail
        """))
        result = extract_description(f)
        assert result != ''
        # Must not return the bare separator '#' or '=' string.
        assert all(c in result for c in ['p', 'u', 's', 'h'])  # "push.sh" in result

    def test_shell_skips_equals_separator(self):
        """# ========= line is skipped; next informative comment is returned."""
        text = '#!/usr/bin/env bash\n# ========================================\n# My script description\n'
        result = _extract_sh_desc(text)
        assert result == 'My script description'
        assert '=' not in result

    def test_shell_skips_dash_separator(self):
        """# --------- line is skipped."""
        text = '#!/usr/bin/env bash\n# ----------------------------------------\n# Another script\n'
        result = _extract_sh_desc(text)
        assert result == 'Another script'

    def test_shell_bare_hash_skipped(self):
        """Bare '#' line is skipped."""
        text = '#!/usr/bin/env bash\n#\n# Real description\n'
        result = _extract_sh_desc(text)
        assert result == 'Real description'

    def test_shell_informative_comment_returned(self):
        """Shell file with directly informative first comment is returned correctly."""
        text = '#!/usr/bin/env bash\n# Validate timeout configuration\n'
        result = _extract_sh_desc(text)
        assert result == 'Validate timeout configuration'

    def test_shell_no_description_falls_back(self):
        """Shell file with only separators falls back to 'Shell script'."""
        text = '#!/usr/bin/env bash\n# ========\n# --------\nset -e\n'
        result = _extract_sh_desc(text)
        assert result == 'Shell script'


# ---------------------------------------------------------------------------
# DEFECT 3: Python docstring scan cap
# ---------------------------------------------------------------------------

class TestPythonDocstringScan:
    """_extract_py_desc must find docstrings beyond line 5."""

    def test_py_docstring_after_line_5(self):
        """Module docstring at line 8 (0-indexed 7) is found despite old i<5 cap."""
        text = (
            '#!/usr/bin/env python3\n'
            '# -*- coding: utf-8 -*-\n'
            '#\n'
            '\n'
            '\n'
            '\n'
            '\n'
            '"""Module that handles important work."""\n'
        )
        result = _extract_py_desc(text)
        assert result == 'Module that handles important work.'
        assert result != 'Python script'

    def test_py_multiline_docstring_after_imports(self):
        """Multi-line docstring at line 10 is captured."""
        text = (
            '#!/usr/bin/env python3\n'
            '# -*- coding: utf-8 -*-\n'
            '#\n'
            '#\n'
            '#\n'
            '#\n'
            '#\n'
            '#\n'
            '#\n'
            '"""\n'
            'Handles batch processing.\n'
            '"""\n'
        )
        result = _extract_py_desc(text)
        assert 'Handles batch processing' in result
        assert result != 'Python script'

    def test_py_encoding_cookie_skipped(self):
        """# -*- coding: utf-8 -*- line is not returned as description."""
        text = '# -*- coding: utf-8 -*-\n"""Real description."""\n'
        result = _extract_py_desc(text)
        assert 'coding' not in result
        assert result == 'Real description.'

    def test_py_stops_at_class_def(self):
        """Scan stops at class/def to avoid returning function docstrings as module desc."""
        text = '#!/usr/bin/env python3\n\ndef foo():\n    """Function docstring."""\n    pass\n'
        result = _extract_py_desc(text)
        # Should return 'Python script' since there's no module-level description
        assert result == 'Python script'

    def test_py_single_line_docstring_early(self):
        """Inline single-line docstring on line 2 is correctly returned."""
        text = '#!/usr/bin/env python3\n"""Quick tool."""\n'
        result = _extract_py_desc(text)
        assert result == 'Quick tool.'


# ---------------------------------------------------------------------------
# DEFECT 4: YAML folded scalar fix
# ---------------------------------------------------------------------------

class TestYamlFoldedScalar:
    """_parse_frontmatter must resolve >- and > block scalar indicators."""

    def test_frontmatter_yaml_folded_scalar(self):
        """description: >-\\n  Multi-word description returns content not '>-'."""
        text = '---\ndescription: >-\n  Multi-word description here\n---\n# content'
        result = _parse_frontmatter(text)
        assert result == 'Multi-word description here'
        assert result != '>-'

    def test_frontmatter_yaml_folded_no_dash(self):
        """description: >\\n  Content is also handled."""
        text = '---\ndescription: >\n  Content text\n---\n'
        result = _parse_frontmatter(text)
        assert result == 'Content text'
        assert result != '>'

    def test_frontmatter_yaml_literal_block(self):
        """description: |\\n  Content handles literal block scalar."""
        text = '---\ndescription: |\n  Literal content\n---\n'
        result = _parse_frontmatter(text)
        assert result == 'Literal content'

    def test_frontmatter_inline_description_unchanged(self):
        """Plain inline description still works correctly."""
        text = '---\ndescription: Simple inline description\n---\n# content'
        result = _parse_frontmatter(text)
        assert result == 'Simple inline description'

    def test_frontmatter_no_frontmatter(self):
        """File without frontmatter returns None."""
        text = '# Just a heading\n'
        result = _parse_frontmatter(text)
        assert result is None

    def test_frontmatter_multi_continuation_lines(self):
        """Multi-line folded scalar joins continuation lines with space."""
        text = '---\ndescription: >-\n  First part\n  second part\n---\n'
        result = _parse_frontmatter(text)
        assert result == 'First part second part'
