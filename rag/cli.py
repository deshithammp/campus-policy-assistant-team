import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from .agent import Agent
from .evaluation import evaluate
from .ingest import PDFIngestor
from .providers import AppleEmbedder, ExtractiveSynthesizer, OfflineEmbedder, OllamaClient, OllamaEmbedder, OllamaSynthesizer
from .retrieval import HybridRetriever, VectorStore


ROOT = Path(__file__).resolve().parent.parent
PROFILES = ('offline', 'semantic', 'ollama')
NSBM_QUESTION = 'Is a mobile phone permitted in the examination room? How do I register for repeat coursework?'


def parser():
    app = argparse.ArgumentParser(description='Campus Policy Assistant — explainable agentic PDF search')
    app.add_argument('--db', type=Path, help='SQLite path (default depends on profile)')
    app.add_argument('--profile', choices=PROFILES)
    commands = app.add_subparsers(dest='command', required=True)
    ingest = commands.add_parser('ingest', help='rebuild the index from a PDF or directory')
    ingest.add_argument('path', type=Path, nargs='?', default=ROOT / 'data/pdfs')
    ask = commands.add_parser('ask', help='answer and trace one question')
    ask.add_argument('question')
    commands.add_parser('chat', help='ask multiple questions in one session')
    evaluation = commands.add_parser('evaluate', help='run the labelled evaluation set')
    evaluation.add_argument('--dataset', type=Path, default=ROOT / 'data/evaluation.json')
    evaluation.add_argument('--output', type=Path, default=ROOT / 'runtime/evaluation.json')
    history = commands.add_parser('history', help='show recent persisted agent runs')
    history.add_argument('--limit', type=int, default=5)
    commands.add_parser('demo', help='index the sample PDFs, answer a two-part question, and evaluate')
    commands.add_parser('nsbm-demo', help='index the NSBM guides, show a two-document answer, and evaluate')
    return app


def config():
    settings = {}
    path = ROOT / '.env'
    if path.is_file():
        for line in path.read_text(encoding='utf-8').splitlines():
            key, separator, value = line.strip().partition('=')
            if separator and key and not key.startswith('#'):
                settings[key.strip()] = value.strip().strip('"\'')
    settings.update(os.environ)
    return settings


def components(profile, settings):
    if profile == 'ollama':
        client = OllamaClient(settings.get('OLLAMA_URL', 'http://127.0.0.1:11434'))
        return (OllamaEmbedder(client, settings.get('OLLAMA_EMBED_MODEL', 'nomic-embed-text')),
                OllamaSynthesizer(client, settings.get('OLLAMA_CHAT_MODEL', 'qwen2.5:3b')))
    if profile == 'semantic':
        helper = Path(settings.get('RAG_APPLE_EMBEDDER', ROOT / 'runtime/apple-embeddings'))
        return AppleEmbedder(helper), ExtractiveSynthesizer()
    return OfflineEmbedder(), ExtractiveSynthesizer()


def ingest(path, store, embedder):
    if path.is_dir():
        files = sorted(item for item in path.iterdir() if item.is_file() and item.suffix.lower() == '.pdf')
    else:
        files = [path] if path.is_file() and path.suffix.lower() == '.pdf' else []
    if not files:
        raise ValueError(f'No PDF files found at {path}.')
    ingestor = PDFIngestor()
    chunks = []
    for pdf in files:
        extracted = ingestor.chunks(pdf)
        chunks.extend(extracted)
        print(f'[Ingest] {pdf.name}: {len(extracted)} chunks')
    vectors = []
    for start in range(0, len(chunks), 24):
        vectors.extend(embedder.embed([chunk.text for chunk in chunks[start:start + 24]]))
    if (len(vectors) != len(chunks) or not vectors[0]
            or any(len(vector) != len(vectors[0]) for vector in vectors)):
        raise ValueError('The embedder returned invalid vector dimensions.')
    store.replace(embedder.signature, list(zip(chunks, vectors)))
    print(f'[Persistence] Saved {len(chunks)} indexed chunks to {store.path}')


def print_event(event):
    print(f'[{event["phase"]}] {event["message"]}', flush=True)
    for candidate in event.get('candidates', []):
        print(f'  {candidate["source"]} | score={candidate["combined"]:.3f} '
              f'| dot={candidate["dot"]:.3f} | ||q||={candidate["query_norm"]:.3f} '
              f'| ||d||={candidate["chunk_norm"]:.3f} | dense cosine={candidate["dense"]:.3f} '
              f'| TF-IDF cosine={candidate["sparse"]:.3f}\n    {candidate["text"]}', flush=True)


def ask(agent, store, question):
    if not question.strip():
        raise ValueError('Enter a question before running a search.')
    result = agent.run(question)
    event = {'phase': 'Persistence', 'message': 'Saving evidence, decisions and answer in SQLite.'}
    result.trace.append(event)
    print_event(event)
    number = store.save_run(result)
    print(f'\nANSWER (run {number})\n{result.answer()}\n')


def run_evaluation(retriever, synthesizer, dataset, output):
    report = evaluate(Agent(retriever, synthesizer), dataset)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f"{'Case':<7} {'Context':>9} {'Grounded':>10} {'Answer':>9} {'Searches':>9}")
    for row in report['rows']:
        scores = row['scores']
        print(f"{row['id']:<7} {_score(scores['context_relevance']):>9} {_score(scores['groundedness']):>10} "
              f"{_score(scores['answer_relevance']):>9} {row['searches']:>9}")
    print('Mean scores: ' + ', '.join(f'{name}={_score(value)}' for name, value in report['averages'].items()))
    print(f'Detailed answers and scores: {output}')


def _score(value):
    return 'N/A' if value is None else f'{value:.3f}'


def main(argv=None):
    args = parser().parse_args(argv)
    settings = config()
    profile = args.profile or settings.get('RAG_PROFILE', 'offline')
    if profile not in PROFILES:
        print(f'Error: unknown RAG profile {profile!r}', file=sys.stderr)
        return 2
    try:
        nsbm_demo = args.command == 'nsbm-demo'
        name = f'nsbm-{profile}' if nsbm_demo else profile
        store = VectorStore(args.db or ROOT / f'runtime/{name}.sqlite3')
        if args.command == 'history':
            if args.limit < 1:
                raise ValueError('History limit must be positive.')
            print(json.dumps(store.recent(args.limit), indent=2, ensure_ascii=False))
            return 0
        embedder, synthesizer = components(profile, settings)
        if args.command in ('demo', 'nsbm-demo', 'ingest'):
            source = ROOT / ('data/nsbm' if nsbm_demo else 'data/pdfs')
            ingest(args.path if args.command == 'ingest' else source, store, embedder)
        if args.command == 'ingest':
            return 0
        retriever = HybridRetriever(store, embedder, dense_weight=0.35 if profile == 'semantic' else 0.65)
        agent = Agent(retriever, synthesizer, print_event)
        if args.command == 'ask':
            ask(agent, store, args.question)
        elif args.command == 'chat':
            print('Ask a policy question. Type /exit to finish.')
            while True:
                question = input('You> ').strip()
                if question == '/exit':
                    break
                if question:
                    ask(agent, store, question)
        elif nsbm_demo:
            ask(agent, store, NSBM_QUESTION)
            run_evaluation(retriever, synthesizer, ROOT / 'data/nsbm-evaluation.json', ROOT / f'runtime/nsbm-{profile}-evaluation.json')
        elif args.command == 'demo':
            ask(agent, store, 'Can I repeat a failed module? How do I register?')
            run_evaluation(retriever, synthesizer, ROOT / 'data/evaluation.json', ROOT / 'runtime/evaluation.json')
        else:
            run_evaluation(retriever, synthesizer, args.dataset, args.output)
        return 0
    except (EOFError, KeyboardInterrupt):
        print()
        return 0
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
