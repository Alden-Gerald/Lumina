import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from local_coder.attachments import FileStore
from document_fixtures import pdf,docx,xlsx,pptx,archive

class AttachmentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=FileStore(Path(self.temp.name))
    def tearDown(self):self.temp.cleanup()

    def test_real_pdf_word_excel_slides_and_csv_extraction(self):
        cases=[('notes.pdf',pdf(['Introduction to circuits.','Calibration voltage is 37.5 volts.']),'Page 2'),
            ('notes.docx',docx(),'Paragraph 1'),('measurements.xlsx',xlsx(),'Sheet Measurements'),
            ('lecture.pptx',pptx(),'Slide 1'),('measurements.csv',b'quantity,value\ncalibration,37.5\n','Lines 1'),
            ('measurements.xls',(Path(__file__).parent/'fixtures/measurements.xls').read_bytes(),'Sheet Measurements')]
        for name,data,location in cases:
            with self.subTest(name=name):
                metadata=self.store.save(data,name);sections=self.store.sections(metadata['id'])
                self.assertEqual(metadata['kind'],'document');self.assertIn('37.5',json.dumps(sections))
                self.assertTrue(any(location in section['location'] for section in sections))
                self.assertEqual(self.store.path(metadata['id']).stat().st_mode&0o777,0o600)
                self.assertEqual(self.store.load(metadata['id']),metadata)
        excel=self.store.sections(self.store.save(xlsx(),'formulas.xlsx')['id'])
        self.assertIn('formula, not evaluated',json.dumps(excel))
        word=self.store.sections(self.store.save(docx(),'table.docx')['id'])
        self.assertIn('Resistance | 12 ohms',json.dumps(word))

    def test_scanned_invalid_unsupported_and_xml_entity_files_fail_clearly(self):
        for name,data in [('blank.pdf',pdf([''])),('fake.pdf',b'not PDF'),('broken.xlsx',b'not ZIP'),('old.doc',b'old Word')]:
            with self.subTest(name=name),self.assertRaises(ValueError):self.store.save(data,name)
        malicious=archive({'word/document.xml':'<!DOCTYPE x [<!ENTITY secret SYSTEM "file:///etc/passwd">]><w:document xmlns:w="w"><w:body><w:p><w:r><w:t>&secret;</w:t></w:r></w:p></w:body></w:document>'})
        with self.assertRaises(ValueError):self.store.save(malicious,'external.docx')
        self.assertFalse(list(self.store.root.glob('*.bin')))

    def test_compressed_bomb_binary_text_size_and_tampering_are_rejected(self):
        bomb=archive({'word/document.xml':'A'*(17*1024**2)})
        with self.assertRaisesRegex(ValueError,'safe extraction'):self.store.save(bomb,'bomb.docx')
        for data in [b'\x00binary',b'X'*(10*1024**2+1)]:
            with self.assertRaises(ValueError):self.store.save(data,'notes.txt')
        m=self.store.save(b'Original lecture content.','notes.txt')
        self.store.path(m['id']).write_bytes(b'Changed')
        with self.assertRaisesRegex(ValueError,'changed'):self.store.load(m['id'])
        m=self.store.save(b'Original lecture content.','notes.txt');(self.store.root/(m['id']+'.text')).write_bytes(b'[]')
        with self.assertRaisesRegex(ValueError,'changed'):self.store.sections(m['id'])
        with self.assertRaises(ValueError):self.store.load('../escape')

    def test_query_retrieval_finds_late_passages_and_respects_budget(self):
        text=('Early unrelated lecture text.\n'*200)+'\nThe nebula calibration constant is 37.5 volts.\n'
        m=self.store.save(text.encode(),'long-notes.txt')
        context,passages=self.store.select([m],'What is the nebula calibration constant?',lambda text:len(text)<2100)
        self.assertIn('37.5',context);self.assertLess(len(context),2100);self.assertLessEqual(len(passages),8)
        self.assertIn('F1:',passages[0]['citation'])
        with self.assertRaisesRegex(ValueError,'context space'):self.store.select([m],'question',lambda _:False)

    def test_four_file_limit_and_document_text_bound(self):
        m=self.store.save(('bounded lecture\n'*20000).encode(),'large.txt')
        self.assertLessEqual(m['characters'],200000);self.assertTrue(m['warnings'])
        with self.assertRaises(ValueError):self.store.validate([m['id']]*2)
        with self.assertRaises(ValueError):self.store.validate(['a'*32]*5)
    def test_summary_selects_coverage_from_both_documents(self):
        documents=[]
        for i in range(2):
            text='\n'.join(f'Topic {n}: '+('Lecture material. '*70) for n in range(12))+'\nFinalTopicMarker'
            documents.append(self.store.save(text.encode(),f'lecture-{i}.txt'))
        context,passages=self.store.select(documents,'Summarize the entire material')
        self.assertEqual({p['file'] for p in passages},{'F1','F2'})
        self.assertIn('FinalTopicMarker',context);self.assertEqual(len(passages),8)
