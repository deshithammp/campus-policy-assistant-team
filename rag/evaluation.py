import json
import re
from statistics import mean

from .text import supported_wording


def contains(text: str, phrase: str) -> bool:
    normal = lambda value: ' '.join(re.findall(r'\w+', value.lower()))
    return f' {normal(phrase)} ' in f' {normal(text)} '


def grounded(claim, evidence: dict) -> bool:
    source = evidence.get(claim.chunk_id)
    if source is None or not claim.quote or claim.quote not in source.text:
        return False
    return supported_wording(claim.text, claim.quote)


def metrics(case, result):
    expected = case['contexts']
    chunks = {hit.chunk.id: hit.chunk for hit in result.evidence}
    found = [{key for key, chunk in chunks.items() if any(
        chunk.document == label['document'] and chunk.page == label['page'] and contains(chunk.text, label['phrase'])
        for label in [item, *item.get('alternatives', [])]
    )} for item in expected]
    if not expected:
        context = float(not chunks)
    else:
        precision = len(set().union(*found)) / len(chunks) if chunks else 0.0
        recall = sum(bool(matches) for matches in found) / len(expected)
        context = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    if result.claims:
        faithfulness = mean(grounded(claim, chunks) for claim in result.claims)
    else:
        faithfulness = None  # No factual claims to score; shown as N/A in aggregates.

    facts = case['required_facts']
    answer_text = ' '.join(claim.text for claim in result.claims)
    checks = [any(contains(answer_text, alternative) for alternative in group) for group in facts]
    checks.extend(any(contains(unanswered, expected) for unanswered in result.missing)
                  for expected in case.get('expected_unanswered', []))
    relevance = mean(checks) if checks else float(not result.claims and bool(result.missing))
    return {'context_relevance': context, 'groundedness': faithfulness, 'answer_relevance': relevance}


def evaluate(agent, dataset_path):
    cases = json.loads(dataset_path.read_text(encoding='utf-8'))
    if not cases:
        raise ValueError('Evaluation dataset is empty.')
    rows = []
    for case in cases:
        result = agent.run(case['question'])
        rows.append({**case, 'answer': result.answer(), 'scores': metrics(case, result),
                     'searches': sum(event['phase'] == 'Observation' for event in result.trace)})
    averages = {}
    for name in rows[0]['scores']:
        values = [row['scores'][name] for row in rows if row['scores'][name] is not None]
        averages[name] = mean(values) if values else None
    return {'rows': rows, 'averages': averages}
