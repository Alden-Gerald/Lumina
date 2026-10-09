import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

from local_coder.server import model_catalog


ROOT = Path(__file__).resolve().parents[1]


class _Ids(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get('id'):
            self.ids.append(values['id'])


class WebUiRegressionTests(unittest.TestCase):
    def test_dashboard_ids_are_unique_and_all_modes_have_content(self):
        html = (ROOT / 'local_coder/web/index.html').read_text()
        parser = _Ids()
        parser.feed(html)
        duplicates = sorted({value for value in parser.ids if parser.ids.count(value) > 1})
        self.assertEqual([], duplicates)
        for required in ('mode-chat', 'mode-code', 'mode-neural-networks',
                         'chat-space', 'composer', 'work', 'neural-space',
                         'context-sidebar', 'context-sidebar-toggle'):
            self.assertIn(required, parser.ids)
        self.assertRegex(html, r'id="context-sidebar"[^>]*hidden')

    def test_neural_tab_does_not_depend_on_missing_inline_metadata(self):
        script = (ROOT / 'local_coder/web/app.js').read_text()
        self.assertNotIn("getElementById('model-metadata')", script)
        self.assertIn("$('mode-neural-networks').onclick", script)
        self.assertIn("initNeuralModels()", script)
        self.assertIn("function renderNeuralGraph", script)
        self.assertIn("class:'neural-link'", script)
        self.assertRegex(script, r"neural-space'\)\.hidden=next!==['\"]neural")
        self.assertIn("allRuns.filter", script)
        self.assertIn('setContextSidebar', script)

    def test_model_catalog_deduplicates_images_and_preserves_roles(self):
        catalog = model_catalog({'qwen3.5:4b', 'qwen3-coder:30b-a3b-q4_K_M'})
        names = [item['model'] for item in catalog]
        self.assertEqual(len(names), len(set(names)))
        shared = next(item for item in catalog if item['model'] == 'qwen3.5:4b')
        self.assertEqual({'Quick chat', 'Image reader'}, set(shared['roles']))
        self.assertTrue(shared['installed'])
        moe = next(item for item in catalog if item['model'] == 'qwen3-coder:30b-a3b-q4_K_M')
        self.assertEqual('mixture-of-experts', moe['architecture'])

    def test_settings_async_sections_have_stale_render_guard(self):
        script = (ROOT / 'local_coder/web/settings.js').read_text()
        self.assertIn('let renderRevision = 0', script)
        self.assertIn('if(!active())return', script)
        self.assertNotRegex(script, r'hydrateSection\(\)')


if __name__ == '__main__':
    unittest.main()
