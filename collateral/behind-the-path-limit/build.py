# -*- coding: utf-8 -*-
"""Rebuild behind-the-path-limit.pptx from behind-the-path-limit.md.

The slides are built with the deck builder of the public "SSDLC in the Mythos
Era" series (https://github.com/edtice-goog/ssdlc-mythos: build-decks.py, its
template and its icons), then the series footer is replaced with this deck's
own so the file does not present itself as part of that series.

    python build.py

The builder is looked for in $SSDLC_MYTHOS, else in a checkout named
ssdlc-mythos beside this repository's checkout. The committed .pptx is the
output of this script at the commit that last changed the markdown; readers
need not rebuild it.
"""
import os, re, subprocess, sys, zipfile, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SERIES = os.environ.get('SSDLC_MYTHOS') or os.path.join(os.path.dirname(REPO), 'ssdlc-mythos')
MD = os.path.join(HERE, 'behind-the-path-limit.md')
OUT = os.path.join(HERE, 'behind-the-path-limit.pptx')
FOOTER_OLD = 'SSDLC in the Mythos Era  ·  '
FOOTER_NEW = 'Behind the Path Limit  ·  '
# The series template carries another deck's title in its metadata.
TITLE = '<dc:title>Behind the Path Limit</dc:title>'

if not os.path.isfile(os.path.join(SERIES, 'build-decks.py')):
    sys.exit('series builder not found at %s: clone https://github.com/edtice-goog/ssdlc-mythos '
             'beside this repository, or set SSDLC_MYTHOS to its path' % SERIES)

r = subprocess.run([sys.executable, 'build-decks.py', MD, '-o', OUT], cwd=SERIES)
if r.returncode:
    sys.exit(r.returncode)

tmp = OUT + '.tmp'
with zipfile.ZipFile(OUT) as src, zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as dst:
    for info in src.infolist():
        data = src.read(info.filename)
        if info.filename.startswith('ppt/slides/slide') and info.filename.endswith('.xml'):
            data = data.decode('utf-8').replace(FOOTER_OLD, FOOTER_NEW).encode('utf-8')
        elif info.filename == 'docProps/core.xml':
            data = re.sub(r'<dc:title>[^<]*</dc:title>', TITLE,
                          data.decode('utf-8')).encode('utf-8')
        dst.writestr(info, data)
shutil.move(tmp, OUT)
print('footer and title relabelled ->', OUT)
