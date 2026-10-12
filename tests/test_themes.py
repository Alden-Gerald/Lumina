import json
from pathlib import Path
import tempfile
import unittest

from local_coder.themes import theme_snapshot


class ThemeSnapshotTests(unittest.TestCase):
    def test_reads_quickshell_choice_and_validates_material_colors(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root/'project'
            source = project/'orbit-shell/config/Theme.qml'
            source.parent.mkdir(parents=True)
            source.write_text('''
                { name: "nord", palette: makePalette(
                    "#171b22", "#242b36", "#303947", "#d8dee9", "#8792a5",
                    "#81a1c1", "#357ec7", "#d08770", "#d6a65f", "#394454", "#bf616a") },
                { name: "material-you", palette: makePalette(
                    materialColors.background, materialColors.surface, materialColors.surfaceHover,
                    materialColors.textPrimary, materialColors.textSecondary, materialColors.accent,
                    materialColors.windows, materialColors.orange, materialColors.warning,
                    materialColors.border, materialColors.danger) }
            ''')
            (project/'colors.json').write_text(json.dumps({'background': '#AABBCC', 'accent': 'not-a-color'}))
            state = root/'state/orbit-shell/theme'
            state.parent.mkdir(parents=True)
            state.write_text('nord\n')
            result = theme_snapshot(project, root/'state')
            palettes = {item['name']: item['palette'] for item in result['themes']}
            self.assertEqual(result['selected'], 'nord')
            self.assertEqual(palettes['nord']['accent'], '#81a1c1')
            self.assertEqual(palettes['material-you']['background'], '#aabbcc')
            self.assertEqual(palettes['material-you']['accent'], '#aac7ff')
            self.assertIn('dracula', palettes)
            state.write_text('unknown-theme\n')
            self.assertEqual(theme_snapshot(project, root/'state')['selected'], 'dracula')


if __name__ == '__main__':
    unittest.main()
