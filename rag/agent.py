import re

from .domain import Claim, Result, Search, Synthesizer
from .text import facets, sentences, terms


class Agent:
    def __init__(self, retriever: Search, synthesizer: Synthesizer, observer=None, min_score: float = 0.12):
        self.retriever = retriever
        self.synthesizer = synthesizer
        self.observer = observer
        self.min_score = min_score

    def run(self, question: str) -> Result:
        result = Result(question)
        targets = facets(question)
        if not targets:
            result.missing = [question]
            return result

        hits = self._search(result, question, limit=4)
        # Inspect the strongest chunk before spending searches on uncovered parts.
        evidence = {target: self._support(target, hits[:1], topic=targets[0]) for target in targets}
        for target, match in evidence.items():
            if match:
                self._record(result, 'Reasoning', f'Evidence found for: {target}', chunk=match[0].chunk.id)
                continue
            self._record(result, 'Reasoning', f'More evidence needed for: {target}')
            query = self._focused_query(target, targets[0])
            self._record(result, 'Action', f'Searching for uncovered evidence: {query}')
            new_hits = self._search(result, query, limit=4)
            evidence[target] = self._support(target, new_hits, topic=targets[0])
            if evidence[target] is None:
                result.missing.append(target)

        selected = {}
        extracts = []
        for match in evidence.values():
            if match:
                hit, quote = match
                selected.setdefault(hit.chunk.id, hit)
                item = Claim(quote, hit.chunk.id, quote)
                if item not in extracts:
                    extracts.append(item)
        result.evidence = list(selected.values())
        self._record(result, 'Action', 'Synthesizing answer from selected passages.' if extracts else 'Returning insufficient evidence.')
        result.claims = self.synthesizer.answer(question, extracts)
        return result

    def _search(self, result, query, limit):
        hits = self.retriever.search(query, limit)
        self._record(result, 'Observation', f'Retrieved {len(hits)} chunks for: {query}', candidates=[{
            'id': hit.chunk.id, 'source': hit.chunk.source, 'text': hit.chunk.text,
            'dot': hit.cosine.dot, 'query_norm': hit.cosine.query_norm, 'chunk_norm': hit.cosine.chunk_norm,
            'dense': hit.cosine.score, 'sparse': hit.sparse, 'combined': hit.score,
        } for hit in hits])
        return hits

    @staticmethod
    def _focused_query(target, first):
        focus = list(dict.fromkeys(terms(target, canonical=True)))
        if target != first and len(focus) < 3:
            focus.extend(word for word in dict.fromkeys(terms(first, canonical=True)) if word not in focus)
        return ' '.join(focus)

    def _support(self, target, hits, topic=''):
        concepts = set(terms(target, canonical=True))
        inherited = set(terms(topic, canonical=True)) - concepts if topic != target and len(concepts) < 3 else set()
        asks_when = target.lower().startswith('when ')
        lookup_words = {'find', 'search', 'obtain', 'locate', 'repository'}
        asks_to_find = 'find' in concepts
        best = None
        best_value = 0.0
        for hit in hits:
            if hit.score < self.min_score:
                continue
            units = [unit for unit in sentences(hit.chunk.text) if not unit.startswith('Fictional sample:')]
            passages = [(unit, 0.0) for unit in units]
            passages.extend((f'{left} {right}', 0.18) for left, right in zip(units, units[1:]))
            contextual_words = set(terms(hit.chunk.text, canonical=True))
            for passage, penalty in passages:
                if passage.rstrip('.!?').lower().endswith(' here'):
                    continue
                words = set(terms(passage, canonical=True))
                overlap = len(words & concepts)
                if not overlap or (inherited and not words & inherited):
                    continue
                coverage = overlap / len(concepts)
                if asks_to_find and not words & lookup_words:
                    continue
                if asks_when:
                    timing = re.search(r'\b(?:until|within|before|after|following|deadline|time|immediately|during|working days|calendar days|\d+th day)\b', passage, re.I)
                    if not timing:
                        continue
                    if overlap >= 2 and len(contextual_words & concepts) >= 0.65 * len(concepts):
                        coverage = max(coverage, 0.70)
                # Long questions include wording that a source may not repeat verbatim.
                # Require three matched concepts and retrieval support before relaxing coverage.
                strong_match = overlap >= 3 and coverage >= 0.50 and hit.score >= 0.28
                if coverage < 0.70 and not strong_match:
                    continue
                value = coverage + 0.12 * hit.score + 0.06 * len(words & inherited) - penalty
                if value > best_value:
                    best = hit, passage
                    best_value = value
        return best

    def _record(self, result, phase, message, **details):
        event = {'phase': phase, 'message': message, **details}
        result.trace.append(event)
        if self.observer:
            self.observer(event)
