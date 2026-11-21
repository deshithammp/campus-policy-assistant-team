# Campus Policy Assistant

An explainable agentic RAG system for DS205.3. It indexes academic PDFs, ranks passages with hybrid retrieval, searches again when a question has missing evidence, and returns cited answers. The NSBM corpus covers examination conduct, extenuating circumstances and repeat coursework.

## Browser interface

On a Mac, double-click **StartWeb.command** in the extracted project folder. From the VS Code terminal, run:

    ./StartWeb.command

The launcher opens [http://127.0.0.1:8765](http://127.0.0.1:8765). Keep the terminal running while using the app. Press Ctrl+C there to stop it. On other platforms, install `requirements.txt` in your Python environment and run `python -m rag.web --open`. If port 8765 is occupied, the launcher selects a free port and prints the new URL.

Ask your own question or choose an example. Click a citation to read the supporting passage and open the cited PDF page or the full document. Offline mode works locally with the PDFs. Select Ollama in the top bar to use the configured local models. The web app uses the NSBM collection when all three source PDFs are present, and labels the fictional sample collection otherwise. Web indexes and question runs are stored locally under `runtime/`. Restart the launcher after changing the source files.

### Manage source PDFs as admin

Set your local admin password once from the project terminal:

    ./StartWeb.command --set-admin-password

On other platforms use `python -m rag.web --set-admin-password` from the configured Python environment. Open **Admin** in the browser, sign in as `admin`, then select and upload one or more PDFs. Uploads can be up to 20 MB and 300 pages per file, and must contain searchable text. Uploads are stored under `runtime/uploads/` and are available to the question engine without a server restart. The first question after a source change loads an index for the current source list.

Under **Source documents**, select **Remove** to exclude an included or uploaded PDF from answers and source links. Select **Restore** to use it again. The file stays on disk and the removal survives a server restart.

The server is local to the computer. Uploaded PDFs appear in the assistant's source list. To replace the admin password, run the password setup command again. Existing sign-ins expire when the password changes.

## Run on a Mac

Open **Start.command** from the extracted project folder. It indexes the source PDFs, runs a two-document example, evaluates 15 labeled questions and opens terminal chat. At **You>**, type your own question. Type **/exit** to finish. Opening through a ZIP preview puts history in a temporary directory.

For the reproducible coursework setup, install **Python 3.10 or newer** and run the following from this folder.

    python3 --version
    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install -r requirements.txt
    cp env.example .env
    python -m rag --profile offline nsbm-demo
    python -m unittest discover -s tests -v

On Windows use the virtual environment activation command for your shell. The portable Python profile works with pypdf. macOS can use the PDFKit fallback when pypdf is unavailable. Evaluations in the report used Python 3.12.16 and pypdf 6.13.0.

## Trained embeddings and optional model generation

On macOS with Swift and the English sentence model available, build the helper and run the measured semantic profile.

    ./SetupModels.command
    ./Start.command semantic

This profile uses the 512-dimensional trained sentence model from Apple's NaturalLanguage framework, hybrid TF-IDF retrieval and extractive, source-linked answers. Other platforms can use the portable offline profile or the optional Ollama profile. To use Ollama, install and start it, pull the two configured models and run the same demo in that profile.

    ollama pull nomic-embed-text
    ollama pull qwen2.5:3b
    python -m rag --profile ollama nsbm-demo

The Ollama profile supplies both neural embeddings and local model synthesis. It validates citations and can fall back to source quotations. Live Ollama generation is outside the verified results for this delivery. The model names and URL can be changed in .env. Changing the embedding model requires rebuilding its index.

## Use and evaluate

    python -m rag --profile offline --db runtime/nsbm-offline.sqlite3 chat
    python -m rag --profile offline --db runtime/nsbm-offline.sqlite3 history --limit 1
    python -m rag --profile offline --db runtime/nsbm-offline.sqlite3 evaluate --dataset data/nsbm-challenge.json --output runtime/challenge.json

Use a different database when indexing your own document folder. PDFs need extractable text or OCR. The synthetic smoke-test corpus remains available through the command **python -m rag demo**.

The official-source files are bundled in the coursework ZIP. A source-only Git checkout uses the [document links](data/nsbm/SOURCES.md). The documents are dated references from the public examinations site. Confirm current procedural details with the institution when needed.

## Coursework files

- [Technical report source](docs/TECHNICAL_REPORT.md) and rendered PDF in the coursework ZIP.
- Development and challenge evaluation sets in the data folder, with measured run outputs in the coursework ZIP.
- [Viva and submission checklist](docs/SUBMISSION.md).
- [Implementation notes](docs/TECHNICAL_NOTES.md) for the original synthetic test fixture.

The public repository and unlisted video require the group's own account access. Use genuine Git commits from each group member and finalize the personal reflection fields before submitting.
