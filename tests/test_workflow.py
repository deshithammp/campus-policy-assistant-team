import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from rag.agent import Agent
from rag.domain import Claim
from rag.evaluation import evaluate, grounded
from rag.ingest import PDFIngestor
from rag.providers import ExtractiveSynthesizer, OfflineEmbedder, OllamaEmbedder, OllamaSynthesizer
from rag.retrieval import HybridRetriever, VectorStore, cosine


DATA = Path(__file__).resolve().parents[1] / 'data'


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.temp.name) / 'test.sqlite3'
        cls.addClassCleanup(cls.temp.cleanup)
        cls.embedder = OfflineEmbedder()
        ingestor = PDFIngestor()
        chunks = [chunk for pdf in sorted((DATA / 'pdfs').glob('*.pdf')) for chunk in ingestor.chunks(pdf)]
        vectors = cls.embedder.embed([chunk.text for chunk in chunks])
        VectorStore(cls.path).replace(cls.embedder.signature, list(zip(chunks, vectors)))

    def agent(self):
        return Agent(HybridRetriever(VectorStore(self.path), self.embedder), ExtractiveSynthesizer())

    def test_followup_uses_two_sources_and_persists(self):
        result = self.agent().run('Can I repeat a failed module? How do I register?')
        self.assertGreater(sum(event['phase'] == 'Observation' for event in result.trace), 1)
        self.assertEqual({hit.chunk.document for hit in result.evidence}, {'assessment-regulations.pdf', 'student-registration.pdf'})
        self.assertEqual(result.missing, [])
        run = VectorStore(self.path).save_run(result)
        self.assertEqual(VectorStore(self.path).recent(1)[0]['id'], run)

    def test_returns_partial_answer_without_inventing_fee(self):
        result = self.agent().run('Can I retake a failed module, and what does the repeat module cost?')
        self.assertIn('next scheduled offering', result.answer())
        self.assertEqual(len(result.claims), 1)
        self.assertIn('what does the repeat module cost', result.missing)

    def test_dataset_and_math(self):
        report = evaluate(self.agent(), DATA / 'evaluation.json')
        self.assertGreaterEqual(len(report['rows']), 10)
        self.assertEqual(report['rows'][0]['scores']['context_relevance'], 1)
        self.assertIsNone(report['rows'][11]['scores']['groundedness'])
        self.assertEqual(cosine([1, 0], [0, 1]).score, 0)
        self.assertEqual(cosine([0, 0], [2, 1]).score, 0)
        self.assertAlmostEqual(cosine([1, 1], [1, 0]).score, 2 ** -0.5)

    def test_rejects_index_with_different_embedding_model(self):
        with self.assertRaisesRegex(ValueError, 'Run ingest'):
            VectorStore(self.path).load('different-model')

    def test_grounding_rejects_changed_number(self):
        result = self.agent().run('When does repeat registration close?')
        claim = result.claims[0]
        source = {hit.chunk.id: hit.chunk for hit in result.evidence}
        self.assertTrue(grounded(claim, source))
        self.assertFalse(grounded(Claim(claim.text.replace('seven', '999'), claim.chunk_id, claim.quote), source))

    def test_ollama_adapter_contract_and_unsupported_claim_fallback(self):
        client = Mock()
        client.post.return_value = {'embeddings': [[0.1, 0.2]]}
        embedder = OllamaEmbedder(client, 'embedding-model')
        self.assertEqual(embedder.embed(['example']), [[0.1, 0.2]])
        client.post.assert_called_once_with('/api/embed', {'model': 'embedding-model', 'input': ['example']})
        quote = 'The deadline is within seven calendar days.'
        source = Claim(quote, 'known', quote)
        client.post.return_value = {'message': {'content': json.dumps({'claims': [
            {'text': 'The deadline is within 999 calendar days.', 'chunk_id': 'known', 'quote': quote}
        ]})}}
        self.assertEqual(OllamaSynthesizer(client, 'chat-model').answer('When is the deadline?', [source]), [source])
        self.assertEqual(client.post.call_args.args[0], '/api/chat')
