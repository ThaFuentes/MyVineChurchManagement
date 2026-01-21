// app/static/js/pastoral/sermon_editor.js
// Full path: WebChurchMan/app/static/js/pastoral/sermon_editor.js
// File name: sermon_editor.js
// Brief, detailed purpose:
//   Client-side logic for Sermon Builder editor.
//   • EXTREME DEBUG MODE: Immediate alert on ANY button click + detailed console logs
//   • If you see the alert → click registered, problem is in card creation
//   • If no alert → script not running or button ID wrong
//   • Hardcoded template – works from empty state
//   • Quill init, remove, word count, serialize

document.addEventListener('DOMContentLoaded', function () {
    console.log('%c[SERMON EDITOR] Script fully loaded and DOM ready', 'color: lime; font-size: 20px; font-weight: bold');

    const sectionsContainer = document.getElementById('sections-container');
    if (!sectionsContainer) {
        console.error('[SERMON EDITOR] FATAL: #sections-container missing');
        alert('FATAL ERROR: sections container not found – template broken');
        return;
    }

    const addFirstBtn = document.getElementById('add-first-section');
    const addSectionBtn = document.getElementById('add-section-btn');

    let quillInstances = [];

    function initQuill(editorEl) {
        console.log('[SERMON EDITOR] Initializing Quill on:', editorEl);
        try {
            const quill = new Quill(editorEl, {
                theme: 'snow',
                modules: { toolbar: true }
            });
            quill.on('text-change', updateWordCount);
            quillInstances.push(quill);
            return quill;
        } catch (err) {
            console.error('[SERMON EDITOR] Quill failed:', err);
            alert('Quill failed – check console');
        }
    }

    // Init existing
    document.querySelectorAll('.quill-editor').forEach(initQuill);

    function createSectionCard() {
        console.log('[SERMON EDITOR] createSectionCard called');
        const html = `
        <div class="section-card mb-5 p-4 border rounded glass-card">
            <div class="section-header d-flex justify-content-between align-items-center mb-3">
                <div class="drag-handle">☰</div>
                <input type="text" class="form-control section-title fw-bold" placeholder="Section Title">
                <select class="form-select section-type w-auto">
                    <option value="introduction">Introduction</option>
                    <option value="point">Point</option>
                    <option value="scripture">Scripture</option>
                    <option value="application">Application</option>
                    <option value="conclusion">Conclusion</option>
                </select>
                <button type="button" class="btn btn-sm btn-danger remove-section">×</button>
            </div>
            <div class="quill-wrapper">
                <div class="quill-editor" style="height: 220px;"></div>
            </div>
            <div class="mt-3">
                <input type="text" class="form-control form-control-sm mb-2" placeholder="Scripture Reference">
                <textarea class="form-control form-control-sm" placeholder="Notes (private)" rows="2"></textarea>
            </div>
        </div>`;

        const div = document.createElement('div');
        div.innerHTML = html.trim();
        const card = div.firstChild;

        const editorEl = card.querySelector('.quill-editor');
        if (editorEl) initQuill(editorEl);

        card.querySelector('.remove-section').addEventListener('click', () => {
            if (confirm('Delete section?')) card.remove();
        });

        console.log('[SERMON EDITOR] Card created successfully');
        return card;
    }

    // ADD FIRST SECTION – MAXIMUM FEEDBACK
    if (addFirstBtn) {
        console.log('%c[SERMON EDITOR] Add First Section button FOUND', 'color: lime; font-size: 18px');
        addFirstBtn.addEventListener('click', function () {
            alert('ADD FIRST SECTION CLICKED! Check console for logs.');
            console.log('%c[ADD FIRST SECTION] CLICK REGISTERED', 'color: yellow; background: black; font-size: 20px');

            sectionsContainer.innerHTML = '';
            console.log('[SERMON EDITOR] Empty state cleared');

            const card = createSectionCard();
            sectionsContainer.appendChild(card);
            console.log('[SERMON EDITOR] New section appended');

            alert('Section added! If you don\'t see it, check browser zoom or scroll.');
        });
    } else {
        console.error('[SERMON EDITOR] BUTTON #add-first-section NOT FOUND');
        alert('ERROR: Add First Section button missing – check template ID');
    }

    // TOOLBAR NEW SECTION
    if (addSectionBtn) {
        addSectionBtn.addEventListener('click', function () {
            alert('TOOLBAR NEW SECTION CLICKED!');
            sectionsContainer.appendChild(createSectionCard());
        });
    }

    // Drag-reorder
    if (sectionsContainer) {
        try {
            new Sortable(sectionsContainer, { handle: '.drag-handle', animation: 150 });
        } catch (err) {
            console.error('Sortable failed:', err);
        }
    }

    function updateWordCount() {
        let total = 0;
        quillInstances.forEach(q => total += q.getText().trim().split(/\s+/).filter(w => w).length);
        document.getElementById('word-count')?.textContent = `${total} words`;
    }
    updateWordCount();

    // Submit
    document.getElementById('sermon-form')?.addEventListener('submit', function () {
        const sections = [];
        document.querySelectorAll('.section-card').forEach((card, i) => {
            const quill = quillInstances.find(q => card.contains(q.container));
            sections.push({
                sort_order: i,
                title: card.querySelector('.section-title').value.trim(),
                section_type: card.querySelector('.section-type').value,
                content: quill ? quill.root.innerHTML : '',
                scripture_reference: card.querySelector('input[placeholder="Scripture Reference"]').value.trim(),
                notes: card.querySelector('textarea').value.trim()
            });
        });
        document.getElementById('sections-json').value = JSON.stringify(sections);
    });
});