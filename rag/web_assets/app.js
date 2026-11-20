const byId = (id) => document.getElementById(id);
const form = byId('question-form');
const question = byId('question');
const mode = byId('mode');
const submit = byId('submit');
const status = byId('status');
const panel = byId('source-panel');
const pdf = byId('pdf');
let sourceTrigger;

function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
}

async function fetchJson(url, options) {
    const response = await fetch(url, options);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Something went wrong. Try again.');
    return data;
}

function showSource(claim, trigger) {
    sourceTrigger = trigger;
    byId('source-title').textContent = claim.document;
    byId('source-page').textContent = `Page ${claim.page} in the original PDF`;
    byId('quote').textContent = claim.quote;
    byId('open-page').href = claim.pageUrl;
    byId('open-document').href = `${claim.documentUrl}#page=${claim.page}`;
    pdf.title = `Page ${claim.page} of ${claim.document}`;
    pdf.src = claim.pageUrl;
    pdf.hidden = !navigator.pdfViewerEnabled;
    panel.hidden = false;
    byId('layout').classList.add('with-source');
    panel.focus({ preventScroll: true });
    panel.scrollIntoView({ block: 'nearest' });
}

function closeSource(restoreFocus) {
    if (panel.hidden) return;
    panel.hidden = true;
    pdf.removeAttribute('src');
    byId('layout').classList.remove('with-source');
    if (restoreFocus) sourceTrigger?.focus();
    sourceTrigger = undefined;
}

byId('close-source').addEventListener('click', () => closeSource(true));
document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeSource(true);
});

function displayAnswer(asked, profile, result) {
    const card = element('article', 'answer');
    const heading = element('div', 'answer-heading');
    heading.append(element('p', 'eyebrow', 'Your question'),
                   element('span', 'answer-mode', profile === 'ollama' ? 'Ollama' : 'Offline'));
    card.append(heading, element('h2', 'asked', asked));

    if (result.claims.length) {
        const claims = element('ul', 'claims');
        for (const claim of result.claims) {
            const item = element('li', 'claim');
            const citation = element('button', 'citation', `${claim.document} · p. ${claim.page} ↗`);
            citation.type = 'button';
            citation.setAttribute('aria-label', `View source evidence from ${claim.document}, page ${claim.page}`);
            citation.addEventListener('click', () => showSource(claim, citation));
            item.append(element('p', '', claim.text), citation);
            claims.append(item);
        }
        card.append(claims);
    }

    if (result.missing.length || !result.claims.length) {
        const missing = element('div', 'missing');
        missing.append(element('strong', '', result.noDocuments ? 'No active source PDFs' : 'Insufficient evidence in the available PDFs'));
        if (result.missing.length && !result.noDocuments) {
            const parts = element('ul');
            for (const part of result.missing) parts.append(element('li', '', part));
            missing.append(parts);
        }
        card.append(missing);
    }
    byId('conversation').prepend(card);
}

form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const asked = question.value.trim();
    if (submit.disabled || !asked) return;
    const profile = mode.value;
    submit.disabled = mode.disabled = question.readOnly = true;
    form.setAttribute('aria-busy', 'true');
    status.classList.remove('error');
    status.textContent = 'Searching policy documents…';
    try {
        const result = await fetchJson('/api/ask', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question: asked, profile }),
        });
        closeSource(false);
        displayAnswer(asked, profile, result);
        question.value = '';
        status.textContent = 'Response ready below.';
    } catch (error) {
        status.classList.add('error');
        status.textContent = error.message;
    } finally {
        submit.disabled = mode.disabled = question.readOnly = false;
        form.removeAttribute('aria-busy');
        question.focus();
    }
});

async function initialize() {
    try {
        const options = await fetchJson('/api/options');
        mode.value = options.profile;
        for (const [label, example] of options.examples) {
            const button = element('button', 'example', `${label} ↗`);
            button.type = 'button';
            button.addEventListener('click', () => {
                if (submit.disabled) return;
                question.value = example;
                form.requestSubmit();
            });
            byId('examples').append(button);
        }
        renderDocuments(options);
        submit.disabled = mode.disabled = false;
    } catch {
        byId('collection').textContent = 'Policy documents unavailable';
        status.classList.add('error');
        status.textContent = 'Could not load the assistant. Start the local server and reload this page.';
    }
}

function renderDocuments(options) {
    const count = options.documents.filter((item) => item.uploaded).length;
    const collection = options.corpus === 'nsbm' ? 'NSBM examination policies' : 'Fictional sample policies';
    byId('collection').textContent = count ? `${collection} + ${count} uploaded` : collection;
    const rows = options.documents.map((item) => {
        const row = element('li');
        const link = element('a', '', item.name);
        link.href = item.url;
        link.target = '_blank';
        link.rel = 'noopener';
        row.append(link);
        return row;
    });
    byId('documents').replaceChildren(...rows);
}

window.addEventListener('focus', async () => {
    try {
        renderDocuments(await fetchJson('/api/options'));
    } catch {
        // The current collection stays visible if the server has stopped.
    }
});

initialize();
