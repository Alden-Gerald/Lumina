"""CPU-only document reader, invoked in a networkless, resource-limited process.

It never runs Office macros, formulas, embedded programs, or external links.
"""
import csv
import io
import json
from pathlib import Path
import re
import resource
import subprocess
import sys
import zipfile

MAX_TEXT=200_000
MAX_UNITS=80
MAX_CELLS=20_000

class Collector:
    def __init__(self):
        self.sections=[];self.chars=0;self.warnings=[];self.units_read=0;self.units_total=0;self.unit='sections'
    def warn(self,message):
        if message not in self.warnings:self.warnings.append(message)
    def add(self,location,text):
        text=text.replace('\x00','').strip()
        if not text:return
        remaining=MAX_TEXT-self.chars
        if len(text)>remaining:self.warn('Text extraction reached the 200,000-character limit; only part of the file is available.')
        if remaining>0:
            self.sections.append({'location':location,'text':text[:remaining]});self.chars+=min(len(text),remaining)
    def result(self):
        if not self.sections:raise ValueError('No readable text was found. For a scanned PDF or diagram, attach a screenshot of the relevant page.')
        return {'sections':self.sections,'characters':self.chars,'warnings':self.warnings,
                'units_read':self.units_read,'units_total':self.units_total,'unit':self.unit}

def office_zip(path,required):
    z=zipfile.ZipFile(path)
    entries=z.infolist()
    if len(entries)>1000 or sum(i.file_size for i in entries)>32*1024**2 or any(i.file_size>16*1024**2 or i.flag_bits&1 for i in entries):
        z.close();raise ValueError('Office archive exceeds the safe extraction limit or is encrypted.')
    if required not in z.namelist():z.close();raise ValueError('File does not match its Office document type.')
    return z

def xml(data):
    from defusedxml.ElementTree import fromstring
    return fromstring(data)

def words(node):
    return ''.join(n.text or '' for n in node.iter() if n.tag.rsplit('}',1)[-1]=='t')

def pdf(path,c):
    if b'%PDF-' not in path.read_bytes()[:1024]:raise ValueError('File is not a valid PDF.')
    info=subprocess.run(['/usr/bin/pdfinfo',str(path)],capture_output=True,timeout=5)
    if info.returncode:raise ValueError('PDF could not be opened. Remove its password or export a new PDF.')
    match=re.search(rb'^Pages:\s+(\d+)',info.stdout,re.M)
    if not match:raise ValueError('PDF page count could not be read.')
    c.unit='pages';c.units_total=int(match[1]);c.units_read=min(c.units_total,MAX_UNITS)
    output=Path('/tmp/pdf-text.txt')
    result=subprocess.run(['/usr/bin/pdftotext','-f','1','-l',str(c.units_read),'-layout','-enc','UTF-8',str(path),str(output)],
                          stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=12)
    if result.returncode:raise ValueError('PDF text extraction failed. Try a smaller, unencrypted PDF.')
    text=output.read_bytes()[:MAX_TEXT*4].decode('utf-8','replace')
    pages=text.split('\f');empty=0
    for i,page in enumerate(pages[:c.units_read],1):
        if not page.strip():empty+=1
        c.add(f'Page {i}',page)
    if empty:c.warn('Some pages have no selectable text. Scans and diagrams need a separate image attachment.')
    if c.units_total>MAX_UNITS:c.warn('Only the first 80 PDF pages were extracted. Split longer documents into sections.')

def docx(path,c):
    with office_zip(path,'word/document.xml') as z:
        root=xml(z.read('word/document.xml'));body=root.find('{*}body');p=0;t=0
        if body is None:raise ValueError('Word document has no body.')
        for block in body:
            if c.chars>=MAX_TEXT:break
            if block.tag.endswith('}tbl'):
                t+=1;rows=[]
                for row in block.findall('{*}tr'):
                    rows.append(' | '.join(words(cell) for cell in row.findall('{*}tc')))
                c.add(f'Table {t}','\n'.join(rows))
            else:
                paragraphs=[block] if block.tag.endswith('}p') else block.findall('.//{*}p')
                for paragraph in paragraphs:
                    p+=1;c.add(f'Paragraph {p}',words(paragraph))
        c.unit='paragraphs/tables';c.units_read=p+t;c.units_total=p+t
        if c.chars>=MAX_TEXT:c.warn('Word text reached the extraction limit; later sections may be missing.')
        for name in sorted(z.namelist()):
            if re.fullmatch(r'word/(footnotes|endnotes|header\d+|footer\d+)\.xml',name):
                c.add(Path(name).stem, '\n'.join(words(p) for p in xml(z.read(name)).findall('.//{*}p')))

def spreadsheet(path,c,legacy=False):
    if legacy:
        import xlrd
        book=xlrd.open_workbook(str(path),on_demand=True);c.units_total=book.nsheets
        sheets=[book.sheet_by_index(i) for i in range(min(book.nsheets,10))]
    else:
        from openpyxl import load_workbook
        # Validate the compressed size before openpyxl expands XML/shared strings.
        with office_zip(path,'xl/workbook.xml'):pass
        book=load_workbook(io.BytesIO(path.read_bytes()),read_only=True,data_only=False,keep_links=False);sheets=book.worksheets;c.units_total=len(sheets)
    c.unit='sheets';cells=0;formulas=False
    try:
        for sheet in sheets[:10]:
            c.units_read+=1;name=sheet.name if legacy else sheet.title
            if legacy:
                rows=([sheet.cell_value(r,col) for col in range(min(sheet.ncols,64))] for r in range(min(sheet.nrows,5000)))
            else:
                # Ignore malicious/inaccurate dimensions; let the XML stream determine real rows.
                sheet.reset_dimensions();rows=sheet.iter_rows(max_row=5000,max_col=64,values_only=True)
            group=[];rownum=0
            for rownum,row in enumerate(rows,1):
                if cells>=MAX_CELLS or c.chars>=MAX_TEXT:break
                values=[]
                for col,value in enumerate(row,1):
                    if value is None or value=='':continue
                    cells+=1
                    if cells>MAX_CELLS:break
                    label='';number=col
                    while number:number,digit=divmod(number-1,26);label=chr(65+digit)+label
                    text=str(value)[:1000]
                    if text.startswith('='):formulas=True;text+=' [formula, not evaluated]'
                    values.append(f'{label}{rownum}: {text}')
                if values:group.append(' | '.join(values))
                if rownum%40==0:
                    c.add(f'Sheet {name} · rows {max(1,rownum-39)}–{rownum}','\n'.join(group));group=[]
            if group:c.add(f'Sheet {name} · ending at row {rownum}','\n'.join(group))
            if (sheet.nrows if legacy else (sheet.max_row or 0))>=5000:c.warn('Rows beyond 5,000 per sheet were omitted.')
            if (sheet.ncols if legacy else (sheet.max_column or 0))>64:c.warn('Columns beyond BL (64 columns) were omitted.')
        if c.units_total>10:c.warn('Only the first 10 sheets were read.')
        c.warn('Reading is limited to the first 5,000 rows and 64 columns per sheet.')
        if cells>=MAX_CELLS:c.warn('Spreadsheet reached its 20,000-cell extraction limit; later cells were omitted.')
        if formulas:c.warn('Formulas are included as text and were not calculated. Charts and embedded images are not read.')
        else:c.warn('Spreadsheet cells were read; charts and embedded images are not read.')
    finally:
        if legacy:book.release_resources()
        else:book.close()

def pptx(path,c):
    with office_zip(path,'ppt/presentation.xml') as z:
        relationships=xml(z.read('ppt/_rels/presentation.xml.rels'))
        targets={n.attrib['Id']:n.attrib['Target'] for n in relationships if n.attrib.get('TargetMode')!='External'}
        presentation=xml(z.read('ppt/presentation.xml'));slides=presentation.findall('.//{*}sldId')
        c.unit='slides';c.units_total=len(slides);c.units_read=min(MAX_UNITS,len(slides))
        for number,slide in enumerate(slides[:MAX_UNITS],1):
            rid=next(v for k,v in slide.attrib.items() if k.endswith('}id'))
            target=targets[rid];name=target.lstrip('/') if target.startswith('/') else 'ppt/'+target
            if '..' in Path(name).parts:raise ValueError('Invalid slide relationship.')
            root=xml(z.read(name))
            c.add(f'Slide {number}','\n'.join(words(p) for p in root.findall('.//{*}p')))
        c.warn('Slide text was read; diagrams, embedded images and speaker notes are not read.')
        if len(slides)>MAX_UNITS:c.warn('Only the first 80 slides were read.')

def plain(path,c,kind):
    data=path.read_bytes()
    try:text=data.decode('utf-8-sig')
    except UnicodeDecodeError:
        if data.startswith((b'\xff\xfe',b'\xfe\xff')):text=data.decode('utf-16')
        else:raise ValueError('Text files must use UTF-8 or UTF-16 encoding.')
    if '\x00' in text:raise ValueError('This is a binary file, not readable text.')
    if kind=='csv':
        rows=csv.reader(io.StringIO(text));lines=[]
        for number,row in enumerate(rows,1):
            if number>5000:c.warn('CSV rows beyond 5,000 were omitted.');break
            lines.append(f'Row {number}: '+' | '.join(cell[:1000] for cell in row[:64]))
        text='\n'.join(lines)
    lines=text.splitlines();c.unit='lines';c.units_total=len(lines)
    for start in range(0,len(lines),40):
        c.add(f'Lines {start+1}–{min(start+40,len(lines))}','\n'.join(lines[start:start+40]));c.units_read=min(start+40,len(lines))
        if c.chars>=MAX_TEXT:break

def main():
    resource.setrlimit(resource.RLIMIT_AS,(256*1024**2,256*1024**2))
    resource.setrlimit(resource.RLIMIT_CPU,(14,15))
    resource.setrlimit(resource.RLIMIT_FSIZE,(2*1024**2,2*1024**2))
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    kind=sys.argv[1];path=Path('/input');c=Collector()
    try:
        if kind=='pdf':pdf(path,c)
        elif kind=='docx':docx(path,c)
        elif kind in {'xlsx','xls'}:spreadsheet(path,c,kind=='xls')
        elif kind=='pptx':pptx(path,c)
        else:plain(path,c,kind)
        print(json.dumps(c.result(),ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'error':str(exc)[:500] or 'Document could not be read. Export it to PDF, DOCX, XLSX or text.'}))

if __name__=='__main__':main()
