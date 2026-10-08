"""Tiny generated, non-personal fixtures for file reader tests."""
import io
import zipfile

def pdf(pages):
    font=3+len(pages)*3
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',
        ('<< /Type /Pages /Count %d /Kids [%s] >>'%(len(pages),' '.join(f'{3+i*3} 0 R' for i in range(len(pages))))).encode()]
    for i,text in enumerate(pages):
        content=('BT /F1 12 Tf 40 740 Td ('+text.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')+') Tj ET').encode()
        objects.extend([f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 {font} 0 R >> >> /Contents {4+i*3} 0 R >>'.encode(),
            f'<< /Length {len(content)} >>\nstream\n'.encode()+content+b'\nendstream',b'<< >>'])
    objects.append(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
    output=b'%PDF-1.4\n';offsets=[0]
    for i,obj in enumerate(objects,1):offsets.append(len(output));output+=f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n'
    start=len(output);output+=f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode()
    output+=b''.join(f'{o:010d} 00000 n \n'.encode() for o in offsets[1:])
    output+=f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode()
    return output

def archive(entries):
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as z:
        for name,text in entries.items():z.writestr(name,text)
    return buffer.getvalue()

def docx():
    return archive({'word/document.xml':'''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
    <w:p><w:r><w:t>Thermodynamics lecture: calibration constant is 37.5 volts.</w:t></w:r></w:p>
    <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Resistance</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>12 ohms</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
    </w:body></w:document>'''})

def xlsx():
    from openpyxl import Workbook
    workbook=Workbook();sheet=workbook.active;sheet.title='Measurements'
    sheet.append(['Quantity','Value']);sheet.append(['Calibration voltage',37.5]);sheet.append(['Resistance',12]);sheet['C4']='=B2/B3'
    buffer=io.BytesIO();workbook.save(buffer);return buffer.getvalue()

def pptx():
    return archive({'ppt/presentation.xml':'<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst></p:presentation>',
        'ppt/_rels/presentation.xml.rels':'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="slides/slide1.xml"/></Relationships>',
        'ppt/slides/slide1.xml':'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:p><a:r><a:t>Calibration voltage: 37.5 volts</a:t></a:r></a:p></p:sld>'})
