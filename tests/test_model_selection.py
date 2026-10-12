import json
from pathlib import Path
import subprocess
import unittest
from local_coder.model_selection import choose
from local_coder.settings import PROFILES

class ModelSelectionTests(unittest.TestCase):
    def test_auto_prefers_reasoning_then_coding_then_short_chat(self):
        self.assertEqual(choose('Explain how these training methods work together',True,ram_gib=24,structured=True)['choice'],'structured')
        self.assertEqual(choose('Explain Python recursion',True,ram_gib=24)['choice'],'study')
        self.assertEqual(choose('Debug my Quickshell QML',False,ram_gib=24)['choice'],'coding')
        self.assertEqual(choose('Hello there',False,ram_gib=24)['choice'],'fast')
        self.assertEqual(choose('Explain eigenvalues',False,ram_gib=24)['choice'],'study')
        self.assertEqual(choose('Hello',False,ram_gib=24,has_documents=True)['choice'],'study')
        self.assertEqual(choose('Hello; continue the problem',False,ram_gib=24,history_chars=2000)['choice'],'study')

    def test_memory_and_installed_models_control_fallbacks(self):
        route=choose('Debug Python code',False,ram_gib=10)
        self.assertEqual(route['choice'],'code14');self.assertIn('RAM budget',route['reason'])
        route=choose('Solve this problem',True,ram_gib=10)
        self.assertEqual(route['choice'],'fast');self.assertTrue(route['thinking'])
        installed=[PROFILES['_chat_fast']['model']]
        self.assertEqual(choose('Explain calculus',True,ram_gib=24,installed=installed)['choice'],'fast')
        for args in [{'installed':[],'ram_gib':24},{'ram_gib':7}]:
            with self.assertRaisesRegex(ValueError,'No suitable'):choose('Explain calculus',True,**args)

    def test_manual_selection_respects_capability_and_capacity(self):
        route=choose('Hello',True,'coding',ram_gib=24)
        self.assertEqual(route['profile'],'power');self.assertFalse(route['thinking'])
        self.assertEqual(choose('Hello',False,'study',ram_gib=24)['choice'],'study')
        for model in ['unknown','coding']:
            with self.assertRaises(ValueError):choose('Hello',True,model,ram_gib=8)
        with self.assertRaises(ValueError):choose('Hello',True,'study',installed=[],ram_gib=24)

    def test_duration_format_at_unit_boundaries(self):
        path=Path(__file__).resolve().parents[1]/'local_coder/web/time-format.js'
        script='const f=require(process.argv[1]); console.log(JSON.stringify([0,10,59,60,70,3599,3600,3915,-5,10.9,Infinity].map(f)));'
        actual=json.loads(subprocess.check_output(['node','-e',script,str(path)],text=True))
        self.assertEqual(actual,['0s','10s','59s','1m 0sec','1m 10sec','59m 59sec','1hr 0min 0sec','1hr 5min 15sec','0s','10s','0s'])
