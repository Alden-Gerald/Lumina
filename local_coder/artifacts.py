"""Extract complete, self-contained HTML artifacts from saved chat replies."""
import re

MAX_ARTIFACT_BYTES = 250_000
WRAPPER = re.compile(r'<local_artifact\b(?P<attrs>[^>]*)>(?P<body>.*?)</local_artifact\s*>', re.I | re.S)
ATTRIBUTE = re.compile(r'([\w-]+)\s*=\s*"([^"]*)"')
HTML_FENCE = re.compile(r'^\s*```html\s*\n(?P<html>.*?)\n```\s*$', re.I | re.S)


def extract_artifact(content):
    """Return the last complete web artifact, or None for partial/invalid output."""
    if not isinstance(content, str):
        return None
    found = None
    for match in WRAPPER.finditer(content):
        attrs = dict(ATTRIBUTE.findall(match.group('attrs')))
        if attrs.get('type') not in {'web_app', 'html'}:
            continue
        fence = HTML_FENCE.fullmatch(match.group('body'))
        if not fence:
            continue
        html = fence.group('html').strip()
        if not html or len(html.encode('utf-8')) > MAX_ARTIFACT_BYTES:
            continue
        if not re.search(r'<(?:!doctype\s+html|html|body)\b', html, re.I):
            continue
        found = {'title': attrs.get('title', 'Untitled artifact')[:100],
                 'identifier': attrs.get('identifier', '')[:100], 'html': html}
    return found
