import json
import re
import subprocess
import sys
from pathlib import Path

from .domain import Chunk
from .text import sentences


class PDFIngestor:
    def __init__(self, max_words: int = 120, overlap_words: int = 20):
        if not 0 <= overlap_words < max_words:
            raise ValueError('Chunk overlap must be smaller than chunk size.')
        self.max_words = max_words
        self.overlap_words = overlap_words

    def chunks(self, path: Path) -> list[Chunk]:
        result = []
        for page, text in enumerate(self._pages(path), start=1):
            text = re.sub(r'-\s*\n\s*(?=[a-z])', '', text)
            text = re.sub(r'(?<=\d)[ \t]+(?=(?:st|nd|rd|th)\b)', '', text)
            text = text.replace('\ufffc', ' ')
            paragraphs = re.split(r'\n\s*\n', text)
            blocks = []
            for paragraph in paragraphs:
                clean = ' '.join(paragraph.split())
                if clean:
                    blocks.extend(self._windows(clean))
            for number, block in enumerate(blocks, start=1):
                result.append(Chunk(f'{path.name}#{page}:{number}', path.name, page, block))
        if not result:
            raise ValueError(f'{path.name} has no extractable text. Run OCR before indexing scanned pages.')
        return result

    def _windows(self, text: str):
        units = []
        for sentence in sentences(text):
            words = sentence.split()
            units.extend(words[start:start + self.max_words] for start in range(0, len(words), self.max_words))
        window = []
        for unit in units:
            if len(window) + len(unit) > self.max_words:
                yield ' '.join(window)
                overlap = min(self.overlap_words, self.max_words - len(unit))
                window = window[-overlap:] if overlap else []
            window.extend(unit)
        if window:
            yield ' '.join(window)

    def _pages(self, path: Path) -> list[str]:
        try:
            from pypdf import PdfReader
        except ModuleNotFoundError as exc:
            if sys.platform != 'darwin':
                raise RuntimeError('Install requirements.txt to extract PDF text on this system.') from exc
            command = ['osascript', '-l', 'JavaScript', str(Path(__file__).with_name('pdfkit.js')), str(path.resolve())]
            result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=60)
            if result.returncode:
                raise ValueError(f'PDFKit could not read {path.name}: {result.stderr.strip()}')
            return json.loads(result.stdout)
        reader = PdfReader(path)
        return [page.extract_text() or '' for page in reader.pages]
