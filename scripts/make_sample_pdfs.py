"""Regenerate original, fictional text PDFs with only the standard library."""
import textwrap
from pathlib import Path


DOCUMENTS = {
    'assessment-regulations.pdf': [
        ('Repeat eligibility', 'Students who fail a module may repeat it at the next scheduled offering after the examination board confirms the result.'),
        ('Medical absence', 'A student who misses an examination for medical reasons must submit the medical absence form and a medical certificate within three working days.'),
        ('Mark review', 'A student may request a mark review within five working days of publication of the provisional result. The review checks calculation and recording errors.'),
        ('Academic appeal', 'An academic appeal may be submitted to the Academic Appeals Office only after the mark review decision. The deadline is ten working days from that decision.'),
    ],
    'student-registration.pdf': [
        ('Repeat registration', 'To register for a repeat module, submit the repeat registration form in the Student Portal and attach the applicable payment receipt.'),
        ('Registration period', 'Repeat registration closes seven calendar days before the teaching period begins.'),
        ('Module withdrawal', 'A student can withdraw from a module without academic penalty during the first two teaching weeks by submitting the module withdrawal form.'),
        ('Timetable clashes', 'For a timetable clash, email the Programme Office and include both module codes and the affected class times.'),
    ],
    'student-support.pdf': [
        ('Accessibility support', 'To request examination accommodations, contact the Accessibility Office with supporting documentation at least four weeks before the examination period.'),
        ('Student ID replacement', 'A replacement student ID card can be requested at the Student Services Desk with a valid photo ID and a completed card replacement form.'),
        ('Enrollment letter', 'Request an enrollment letter through the Student Records Portal. The standard processing time is two working days.'),
        ('Official transcript', 'Request an official transcript through the Student Records Portal using the transcript request form. The standard processing time for a transcript is five working days.'),
    ],
}


def escape(value):
    return value.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')


def write_pdf(path, sections):
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'', b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    pages = []
    for title, paragraph in sections:
        page_id = len(objects) + 1
        pages.append(f'{page_id} 0 R')
        content = ['BT /F1 12 Tf 17 TL 65 685 Td']
        content.extend(f'({escape(line)}) Tj T*' for line in textwrap.wrap(paragraph, width=78))
        content.extend(['ET', f'BT /F1 11 Tf 65 55 Td (Fictional sample: {escape(title)}.) Tj ET'])
        stream = '\n'.join(content).encode('ascii')
        objects.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {page_id + 1} 0 R >>'.encode())
        objects.append(f'<< /Length {len(stream)} >>\nstream\n'.encode() + stream + b'\nendstream')
    objects[1] = f'<< /Type /Pages /Count {len(pages)} /Kids [{" ".join(pages)}] >>'.encode()
    pdf = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f'{number} 0 obj\n'.encode() + obj + b'\nendobj\n')
    xref = len(pdf)
    pdf.extend(f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:
        pdf.extend(f'{offset:010d} 00000 n \n'.encode())
    pdf.extend(f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
    path.write_bytes(pdf)


if __name__ == '__main__':
    directory = Path(__file__).resolve().parents[1] / 'data/pdfs'
    directory.mkdir(parents=True, exist_ok=True)
    for name, sections in DOCUMENTS.items():
        write_pdf(directory / name, sections)
