import re


STOP = set('a an and are as at be by can candidate candidates could did do does for from had has have how i if in is it me my of on or our should so than that the their them then there these they this to under was were must need following what when where which who why will with would you your'.split())
ALIASES = {
    'apply': 'submit', 'application': 'submit', 'applying': 'submit', 'submitted': 'submit', 'submitting': 'submit',
    'submission': 'submit', 'enrol': 'register', 'enroll': 'register',
    'registration': 'register', 'registering': 'register', 'registered': 'register',
    'deadline': 'due', 'deadlines': 'due', 'close': 'due', 'closes': 'due',
    'failed': 'fail', 'fails': 'fail', 'failing': 'fail', 'failure': 'fail',
    'retake': 'repeat', 'resit': 'repeat', 'resitting': 'repeat', 'repeating': 'repeat',
    'permitted': 'eligible', 'eligibility': 'eligible', 'allowed': 'eligible',
    'absence': 'miss', 'missed': 'miss', 'missing': 'miss', 'absent': 'miss',
    'ill': 'medical', 'illness': 'medical', 'sick': 'medical',
    'certificate': 'evidence', 'proof': 'evidence', 'documentation': 'evidence',
    'officer': 'office', 'dropped': 'withdraw', 'drop': 'withdraw',
    'order': 'request', 'processing': 'process', 'appealing': 'appeal', 'appeals': 'appeal', 'examination': 'exam',
    'examinations': 'exam', 'exams': 'exam', 'modules': 'module',
    'accepted': 'accept', 'accepts': 'accept', 'papers': 'paper', 'reviews': 'review',
    'tells': 'instruct', 'told': 'instruct', 'instructed': 'instruct', 'admitted': 'enter',
    'smoke': 'smoking', 'assignment': 'coursework', 'assignments': 'coursework',
    'downloaded': 'download', 'downloading': 'download', 'claims': 'claim',
    'students': 'student', 'fees': 'fee', 'cost': 'fee', 'costs': 'fee', 'results': 'result', 'marks': 'mark',
}


def terms(text: str, *, canonical: bool = False) -> list[str]:
    text = text.lower()
    if canonical:
        text = re.sub(r'\bhow long does it take to process\b', 'processing time', text)
        text = re.sub(r'\bextenuating circumstances\b', 'ec', text)
    words = re.findall(r"[a-z0-9]+", text)
    return [ALIASES.get(word, word) if canonical else word for word in words if word not in STOP]


def sentences(text: str) -> list[str]:
    return [item.strip() for item in re.split(r'(?<=[.!?])\s+', text) if item.strip()]


def facets(question: str) -> list[str]:
    parts = re.split(r'\?\s*|\s*;\s*|\s+and\s+(?:also\s+)?(?=(?:how|where|when|what|who|which)\s)', question, flags=re.I)
    return [part.strip(' ,.') for part in parts if terms(part)]


def supported_wording(answer: str, quote: str) -> bool:
    answer_words = set(terms(answer, canonical=True))
    quote_words = set(terms(quote, canonical=True))
    numbers = set(re.findall(r'\b\d+(?:[.:]\d+)?\b', answer))
    quote_numbers = set(re.findall(r'\b\d+(?:[.:]\d+)?\b', quote))
    markers = {'no', 'not', 'never', 'without', 'before', 'after', 'only', 'least', 'within'}
    return (bool(answer_words) and numbers <= quote_numbers
            and (set(re.findall(r'\w+', answer.lower())) & markers) == (set(re.findall(r'\w+', quote.lower())) & markers)
            and len(answer_words & quote_words) / len(answer_words) >= 0.8)
