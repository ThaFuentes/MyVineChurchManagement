// app/static/js/global/pastoral/illustrations.js
// Full path: WebChurchMan/app/static/js/global/pastoral/illustrations.js
// File name: illustrations.js
// Brief, detailed purpose:
//   Illustrations sidebar functionality in the Sermon Editor.
//   - On load: Fetch recent/shared illustrations (visible to user) for quick access
//   - Search: Input → filter library (server could enhance later)
//   - "Insert" button per illustration → POST JSON to /illustrations/insert/<sermon_id>
//   - Server returns pre-formatted HTML block (title, blockquote, source)
//   - Insert HTML into active Quill editor at cursor (via SermonEditor.getActiveQuill)
//   - Toolbar button focuses search input

document.addEventListener('DOMContentLoaded', () => {
    const searchInput = document.getElementById('illus-search');
    const illusList = document.getElementById('illus-list');
    const insertIllustrationBtn = document.getElementById('insert-illustration-btn'); // Toolbar button

    const sermonId = document.body.dataset.sermonId || null; // Must exist for insert endpoint

    if (!illusList || !sermonId) return;

    // Load recent illustrations on init
    async function loadIllustrations(query = '') {
        illusList.innerHTML = '<p class="text-muted small">Loading...</p>';

        try {
            // Simple GET with query param (route can add search later)
            const url = `/pastoral/illustrations/library_data?sermon_id=${sermonId}${query ? '&search=' + encodeURIComponent(query) : ''}`;
            const resp = await fetch(url);
            if (!resp.ok) throw new Error('Load failed');

            const data = await resp.json(); // Expect {illustrations: [...]}
            displayIllustrations(data.illustrations || []);
        } catch (err) {
            illusList.innerHTML = '<p class="text-danger small">Failed to load illustrations.</p>';
        }
    }

    function displayIllustrations(illustrations) {
        if (illustrations.length === 0) {
            illusList.innerHTML = '<p class="text-muted small">No illustrations found.</p>';
            return;
        }

        let html = '';
        illustrations.forEach(illus => {
            html += `
                <div class="illustration-card mb-3 p-3 border rounded glass-card">
                    <strong class="d-block mb-1">${illus.title}</strong>
                    <p class="small text-muted mb-2">${illus.content.substring(0, 150)}${illus.content.length > 150 ? '...' : ''}</p>
                    ${illus.source ? `<em class="small text-muted d-block mb-2">Source: ${illus.source}</em>` : ''}
                    <button class="btn btn-sm btn-cyan insert-illus-btn w-100" data-id="${illus.id}">
                        Insert into Sermon
                    </button>
                </div>
            `;
        });
        illusList.innerHTML = html;

        // Bind insert buttons
        document.querySelectorAll('.insert-illus-btn').forEach(btn => {
            btn.addEventListener('click', () => insertIllustration(btn.dataset.id));
        });
    }

    async function insertIllustration(illusId) {
        const btn = document.querySelector(`.insert-illus-btn[data-id="${illusId}"]`);
        if (btn) btn.disabled = true;
        btn.innerHTML = 'Inserting...';

        try {
            const resp = await fetch(`/pastoral/illustrations/insert/${sermonId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ illustration_id: parseInt(illusId) })
            });

            if (!resp.ok) throw new Error('Insert failed');

            const data = await resp.json();
            const quill = window.SermonEditor?.getActiveQuill();
            if (!quill || !data.html) throw new Error('No editor or HTML');

            const range = quill.getSelection() || { index: quill.getLength() };
            quill.clipboard.dangerouslyPasteHTML(range.index, data.html);
            quill.setSelection(range.index + data.html.length);
        } catch (err) {
            alert('Failed to insert illustration – try again.');
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = 'Insert into Sermon';
            }
        }
    }

    // Search handler
    if (searchInput) {
        let searchTimeout;
        searchInput.addEventListener('input', () => {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => loadIllustrations(searchInput.value.trim()), 500);
        });
    }

    // Toolbar button focuses search
    if (insertIllustrationBtn) {
        insertIllustrationBtn.addEventListener('click', () => {
            searchInput.focus();
        });
    }

    // Initial load
    loadIllustrations();
});