const byId = (id) => document.getElementById(id);
const status = byId('admin-status');
const signIn = byId('sign-in');
const signOut = byId('sign-out');
const upload = byId('upload');
let csrf;
let documentsBusy = false;
let canManageSources = true;

function message(text, error = false) {
    status.textContent = text;
    status.classList.toggle('error', error);
}

async function request(url, options) {
    const response = await fetch(url, options);
    const isJson = response.headers.get('Content-Type')?.includes('application/json');
    const data = isJson ? await response.json() : null;
    if (!response.ok || !data) {
        const error = new Error(data?.error || 'The local server could not complete the request.');
        error.status = response.status;
        throw error;
    }
    return data;
}

function documents(items) {
    const rows = items.map((item) => {
        const row = document.createElement('li');
        const label = document.createElement(item.removed ? 'span' : 'a');
        if (!item.removed) {
            label.href = item.url;
            label.target = '_blank';
            label.rel = 'noopener';
        }
        label.textContent = item.name;
        const actions = document.createElement('div');
        actions.className = 'document-actions';
        const kind = document.createElement('span');
        kind.textContent = item.removed ? 'Removed' : (item.uploaded ? 'Uploaded' : 'Included');
        actions.append(kind);
        if (canManageSources) {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'example source-action';
            button.disabled = documentsBusy;
            button.textContent = item.removed ? 'Restore' : 'Remove';
            button.setAttribute('aria-label', `${button.textContent} ${item.name}`);
            button.dataset.sourceName = item.name;
            button.addEventListener('click', () => changeSource(item));
            actions.append(button);
        }
        row.append(label, actions);
        return row;
    });
    byId('admin-documents').replaceChildren(...rows);
}

function lockDocuments(busy) {
    documentsBusy = busy;
    byId('files').disabled = upload.querySelector('button').disabled = signOut.disabled = busy;
    for (const action of byId('admin-documents').querySelectorAll('button')) action.disabled = busy;
}

async function changeSource(item) {
    lockDocuments(true);
    let expired = false;
    try {
        const result = await request('/api/admin/source', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
            body: JSON.stringify({ name: item.name, removed: !item.removed }),
        });
        documents(result.documents);
        message(item.removed ? `${item.name} is available for new answers.` :
            `${item.name} was removed from the sources. You can restore it here.`);
    } catch (error) {
        expired = error.status === 401;
        if (expired) showScreen(true, null);
        message(error.message, true);
    } finally {
        lockDocuments(false);
        if (expired) byId('password').focus();
        else {
            const actions = [...byId('admin-documents').querySelectorAll('button')];
            actions.find((action) => action.dataset.sourceName === item.name)?.focus();
        }
    }
}

function showScreen(configured, token) {
    csrf = token;
    byId('setup').hidden = configured;
    signIn.hidden = !configured || Boolean(csrf);
    byId('dashboard').hidden = !csrf;
    signOut.hidden = !csrf;
}

async function loadDocuments() {
    try {
        const result = await request('/api/admin/documents');
        canManageSources = true;
        documents(result.documents);
        message('');
    } catch (error) {
        if (error.status !== 404) throw error;
        const result = await request('/api/options');
        canManageSources = false;
        documents(result.documents);
        message('This is an older server session. Restart the app to enable Remove and Restore.');
    }
}

async function load() {
    try {
        const session = await request('/api/admin/status');
        showScreen(session.configured, session.csrf);
        message('');
        if (csrf) await loadDocuments();
        return session.configured;
    } catch (error) {
        message(error.message, true);
        return false;
    }
}

byId('check-setup').addEventListener('click', async () => {
    if (await load()) byId('password').focus();
    else message('Set the password in the project terminal, then try again.', true);
});

signIn.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = signIn.querySelector('button');
    button.disabled = true;
    message('Signing in…');
    try {
        const result = await request('/api/admin/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: byId('username').value.trim(), password: byId('password').value }),
        });
        showScreen(true, result.csrf);
        await loadDocuments();
        byId('files').focus();
    } catch (error) {
        message(error.message, true);
    } finally {
        byId('password').value = '';
        button.disabled = false;
    }
});

signOut.addEventListener('click', async () => {
    try {
        await request('/api/admin/logout', { method: 'POST', headers: { 'X-CSRF-Token': csrf } });
        showScreen(true, null);
        upload.reset();
        byId('upload-results').replaceChildren();
        message('Signed out.');
        byId('password').focus();
    } catch (error) {
        if (error.status === 401) showScreen(true, null);
        message(error.message, true);
    }
});

upload.addEventListener('submit', async (event) => {
    event.preventDefault();
    const input = byId('files');
    const files = [...input.files];
    const results = byId('upload-results');
    results.replaceChildren();
    lockDocuments(true);
    let completed = 0;
    try {
        for (const file of files) {
            message(`Checking ${file.name}…`);
            const row = document.createElement('li');
            try {
                if (file.size === 0 || file.size > 20 * 1024 ** 2) {
                    throw new Error('Choose a non-empty PDF up to 20 MB.');
                }
                const query = new URLSearchParams({ name: file.name });
                const result = await request(`/api/admin/upload?${query}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/pdf', 'X-CSRF-Token': csrf },
                    body: file,
                });
                documents(result.documents);
                row.textContent = `${file.name} · Uploaded`;
                completed++;
            } catch (error) {
                if (error.status === 401) {
                    showScreen(true, null);
                    message('Session expired. Sign in again to continue.', true);
                    byId('password').focus();
                    return;
                }
                row.className = 'error';
                row.textContent = `${file.name} · ${error.message}`;
            }
            results.append(row);
        }
        message(completed === files.length ? 'Upload complete. You can now ask about these PDFs.' :
            `${completed} of ${files.length} PDFs uploaded. See details below.`, completed === 0);
    } finally {
        lockDocuments(false);
        input.value = '';
    }
});

load();
