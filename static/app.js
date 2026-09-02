// State & Initialization
document.addEventListener('DOMContentLoaded', () => {
    initTabs();
    initChat();
    initReviewQueue();
    initContractsExplorer();
    fetchStats();
});

// Toast notification helper
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    
    let icon = 'ℹ️';
    if (type === 'success') icon = '✅';
    if (type === 'danger') icon = '⚠️';
    
    toast.innerHTML = `<span>${icon}</span> <span>${message}</span>`;
    container.appendChild(toast);
    
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(10px)';
        toast.style.transition = 'all 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// Tab Switching
function initTabs() {
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');

    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetId = btn.getAttribute('data-tab');
            
            tabBtns.forEach(b => b.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));
            
            btn.classList.add('active');
            document.getElementById(targetId).classList.add('active');

            if (targetId === 'tab-review') {
                loadReviewQueue();
            } else if (targetId === 'tab-contracts') {
                loadContracts();
            }
        });
    });
}

// Fetch Global Stats
async function fetchStats() {
    try {
        const res = await fetch('/stats');
        if (res.ok) {
            const data = await res.json();
            document.getElementById('stat-contracts-count').innerText = data.contracts_count || '21';
            document.getElementById('stat-chunks-count').innerText = data.chunks_count || '640+';
            
            const badge = document.getElementById('review-badge');
            if (data.pending_reviews > 0) {
                badge.style.display = 'inline-block';
                badge.innerText = data.pending_reviews;
            } else {
                badge.style.display = 'none';
            }
        }
    } catch (err) {
        console.error('Failed to load stats', err);
    }
}

// Interactive Chat & Assistant Logic
function initChat() {
    const input = document.getElementById('query-input');
    const sendBtn = document.getElementById('send-btn');
    const samplePills = document.querySelectorAll('.prompt-pill');

    samplePills.forEach(pill => {
        pill.addEventListener('click', () => {
            input.value = pill.getAttribute('data-query');
            input.focus();
        });
    });

    sendBtn.addEventListener('click', handleSend);
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    });

    async function handleSend() {
        const question = input.value.trim();
        if (!question) return;

        input.value = '';
        appendMessage('user', question);

        sendBtn.disabled = true;
        sendBtn.innerHTML = '<span class="spinner"></span> Processing...';

        // Update pipeline side panel to active
        setPipelineActive(true);

        try {
            const res = await fetch('/questions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ question })
            });

            const data = await res.json();
            handleAssistantResponse(data);
            fetchStats();
        } catch (err) {
            appendMessage('assistant', `⚠️ Error processing request: ${err.message}`);
            showToast('Request failed. Check server logs.', 'danger');
        } finally {
            sendBtn.disabled = false;
            sendBtn.innerHTML = 'Send Query <span>↵</span>';
            setPipelineActive(false);
        }
    }
}

function setPipelineActive(active) {
    const steps = document.querySelectorAll('.step-item');
    steps.forEach((s, idx) => {
        if (active) {
            setTimeout(() => s.classList.add('active'), idx * 250);
        } else {
            s.classList.remove('active');
        }
    });
}

function appendMessage(sender, text) {
    const chatHistory = document.getElementById('chat-history');
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${sender}`;

    const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    msgDiv.innerHTML = `
        <div class="msg-bubble">${escapeHtml(text)}</div>
        <div class="msg-meta">
            <span>${sender === 'user' ? 'You' : 'Contract Assistant'}</span>
            <span>•</span>
            <span>${time}</span>
        </div>
    `;

    chatHistory.appendChild(msgDiv);
    chatHistory.scrollTop = chatHistory.scrollHeight;
    return msgDiv;
}

function handleAssistantResponse(data) {
    const chatHistory = document.getElementById('chat-history');
    const msgDiv = document.createElement('div');
    msgDiv.className = 'message assistant';

    const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    let contentHtml = '';

    if (data.type === 'auto_answer') {
        contentHtml = `
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.6rem;">
                <span class="status-tag auto_answer">✓ Auto Answered</span>
                <span style="font-size:0.75rem; color:var(--success);">High Confidence & Low Risk</span>
            </div>
            <p style="font-size:0.95rem; font-weight:500; color:#fff;">${escapeHtml(data.answer)}</p>
        `;

        if (data.retrieved_chunks && data.retrieved_chunks.length > 0) {
            contentHtml += `
                <div class="citations-container">
                    <div style="font-size:0.75rem; color:var(--text-muted); font-weight:600; text-transform:uppercase;">
                        Retrieved Context & Section Citations (${data.retrieved_chunks.length})
                    </div>
                    ${data.retrieved_chunks.map((c, i) => `
                        <div class="citation-card">
                            <div class="citation-header">
                                <span>📄 ${escapeHtml(c.vendor_name || c.contract_file)} &bull; Section ${escapeHtml(c.section_number || 'General')}</span>
                                <span class="citation-score">Cosine Similarity: ${(c.score ? c.score.toFixed(4) : 'N/A')}</span>
                            </div>
                            <div class="citation-text">${escapeHtml(c.chunk_text)}</div>
                        </div>
                    `).join('')}
                </div>
            `;
        }
    } else if (data.type === 'clarifying_question') {
        contentHtml = `
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.6rem;">
                <span class="status-tag ambiguous">❓ Ambiguity Detected</span>
                <span style="font-size:0.75rem; color:#93c5fd;">Multiple Contracts Matched</span>
            </div>
            <p style="font-size:0.95rem; font-weight:500; color:#fff;">${escapeHtml(data.clarifying_question)}</p>
            <div class="candidate-buttons" id="candidate-btns-${Date.now()}"></div>
        `;
    } else if (data.type === 'pending_review') {
        contentHtml = `
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.6rem;">
                <span class="status-tag queue_for_review">⏳ Routed to Review Queue</span>
                <span style="font-size:0.75rem; color:var(--warning);">Ticket #${data.pending_review_id}</span>
            </div>
            <p style="font-size:0.92rem; color:var(--text-secondary); margin-bottom:0.5rem;">
                This query involves a high-risk clause or fell below the automated confidence threshold. A draft answer has been placed in the Human-in-the-Loop review queue.
            </p>
            <div class="review-reason">
                <strong>Routing Reason:</strong> ${escapeHtml(data.risk_reason || 'High risk category')}
            </div>
        `;
    }

    msgDiv.innerHTML = `
        <div class="msg-bubble">${contentHtml}</div>
        <div class="msg-meta">
            <span>Contract Assistant (Gemini 2.5 Flash + pgvector)</span>
            <span>•</span>
            <span>${time}</span>
        </div>
    `;

    chatHistory.appendChild(msgDiv);
    chatHistory.scrollTop = chatHistory.scrollHeight;

    // If ambiguous, parse candidate vendor names and add interactive click pills
    if (data.type === 'clarifying_question' && data.clarifying_question) {
        parseCandidateVendors(data.clarifying_question, msgDiv);
    }
}

function parseCandidateVendors(questionText, msgDiv) {
    const match = questionText.match(/Candidates:\s*([^?]+)/i);
    if (match && match[1]) {
        const rawVendors = match[1].split(/,|\bor\b/i).map(v => v.trim()).filter(v => v.length > 1);
        const container = msgDiv.querySelector('.candidate-buttons');
        if (container) {
            rawVendors.forEach(vendor => {
                const btn = document.createElement('button');
                btn.className = 'candidate-btn';
                btn.innerText = `Select ${vendor}`;
                btn.onclick = () => {
                    const input = document.getElementById('query-input');
                    input.value = `What are the terms for ${vendor}?`;
                    input.focus();
                };
                container.appendChild(btn);
            });
        }
    }
}

// Human-in-the-loop (HITL) Review Queue
async function loadReviewQueue() {
    const grid = document.getElementById('review-queue-grid');
    grid.innerHTML = '<div style="color:var(--text-muted);"><span class="spinner"></span> Loading review queue...</div>';

    try {
        const res = await fetch('/review-queue');
        const items = await res.json();

        if (!items || items.length === 0) {
            grid.innerHTML = `
                <div style="grid-column: 1 / -1; padding: 3rem; text-align: center; color: var(--text-muted); background: var(--bg-card); border-radius: var(--radius-lg); border: 1px solid var(--border-color);">
                    <div style="font-size: 2.5rem; margin-bottom: 0.5rem;">🎉</div>
                    <div style="font-size: 1.1rem; font-weight: 600; color: var(--text-primary);">Review Queue is Clear!</div>
                    <div style="font-size: 0.85rem; margin-top: 0.25rem;">All high-risk contract queries have been resolved.</div>
                </div>
            `;
            return;
        }

        grid.innerHTML = '';
        items.forEach(item => {
            const card = document.createElement('div');
            card.className = 'review-card';
            card.id = `review-item-${item.id}`;

            card.innerHTML = `
                <div class="review-header">
                    <div>
                        <div style="font-size: 0.75rem; color: var(--warning); font-weight: 700; margin-bottom: 0.25rem;">ITEM #${item.id}</div>
                        <div class="review-question">${escapeHtml(item.question)}</div>
                    </div>
                    <span class="status-tag ${item.status}">${item.status}</span>
                </div>
                
                <div class="review-reason">
                    <strong>Trigger:</strong> ${escapeHtml(item.risk_reason || 'High Risk')}
                </div>

                <div>
                    <div style="font-size: 0.75rem; color: var(--text-muted); font-weight: 600; text-transform: uppercase; margin-bottom: 0.35rem;">Draft Generated Answer (Editable)</div>
                    <textarea class="review-draft editable" id="draft-input-${item.id}">${escapeHtml(item.draft_answer || '')}</textarea>
                </div>

                ${item.retrieved_chunks && item.retrieved_chunks.length > 0 ? `
                    <div>
                        <div style="font-size: 0.75rem; color: var(--text-muted); font-weight: 600; text-transform: uppercase; margin-bottom: 0.35rem;">Top Context Citations (${item.retrieved_chunks.length})</div>
                        <div style="max-height: 120px; overflow-y: auto; display: flex; flex-direction: column; gap: 0.4rem;">
                            ${item.retrieved_chunks.map(c => `
                                <div style="background: rgba(0,0,0,0.2); padding: 0.4rem 0.6rem; border-radius: var(--radius-sm); font-size: 0.75rem; font-family: var(--font-mono); color: var(--text-secondary);">
                                    <span style="color: var(--accent-primary); font-weight:600;">${escapeHtml(c.vendor_name || c.contract_file)} (Sec ${escapeHtml(c.section_number || 'General')}):</span>
                                    ${escapeHtml(c.chunk_text.slice(0, 150))}...
                                </div>
                            `).join('')}
                        </div>
                    </div>
                ` : ''}

                <div class="review-actions">
                    <button class="btn btn-success" onclick="resolveReview(${item.id}, 'approve')">✓ Approve</button>
                    <button class="btn btn-secondary" onclick="resolveReview(${item.id}, 'edit')">✎ Save Edit</button>
                    <button class="btn btn-danger" onclick="resolveReview(${item.id}, 'reject')">✕ Reject</button>
                </div>
            `;

            grid.appendChild(card);
        });
    } catch (err) {
        grid.innerHTML = `<div style="color:var(--danger);">Error loading review queue: ${err.message}</div>`;
    }
}

async function resolveReview(id, decision) {
    const draftTextarea = document.getElementById(`draft-input-${id}`);
    const finalAnswer = draftTextarea ? draftTextarea.value.trim() : '';

    try {
        const res = await fetch(`/review-queue/${id}/decision`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                decision: decision,
                final_answer: finalAnswer,
                note: `Resolved via Web UI (${decision})`
            })
        });

        if (res.ok) {
            showToast(`Review #${id} ${decision}d successfully!`, 'success');
            const card = document.getElementById(`review-item-${id}`);
            if (card) {
                card.style.opacity = '0';
                card.style.transform = 'scale(0.95)';
                card.style.transition = 'all 0.3s ease';
                setTimeout(() => card.remove(), 300);
            }
            fetchStats();
        } else {
            const err = await res.json();
            showToast(`Action failed: ${err.detail || 'Server error'}`, 'danger');
        }
    } catch (err) {
        showToast(`Error submitting decision: ${err.message}`, 'danger');
    }
}

// Contracts Explorer
async function loadContracts() {
    const tbody = document.getElementById('contracts-table-body');
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:2rem; color:var(--text-muted);"><span class="spinner"></span> Loading contracts...</td></tr>';

    try {
        const res = await fetch('/contracts');
        const contracts = await res.json();

        if (!contracts || contracts.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:2rem;">No contracts found in database.</td></tr>';
            return;
        }

        tbody.innerHTML = contracts.map(c => `
            <tr>
                <td style="font-weight:600; color:var(--text-primary);">${escapeHtml(c.vendor_name || 'N/A')}</td>
                <td><span class="badge-source ${c.source}">${escapeHtml(c.source)}</span></td>
                <td>${escapeHtml(c.agreement_type || 'Agreement')}</td>
                <td style="font-family:var(--font-mono); font-size:0.8rem;">${escapeHtml(c.contract_file)}</td>
                <td>
                    <button class="btn btn-secondary" style="padding:0.3rem 0.6rem; font-size:0.75rem;" onclick="queryForContract('${escapeHtml(c.vendor_name || c.contract_file)}')">
                        Ask Questions 💬
                    </button>
                </td>
            </tr>
        `).join('');
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="5" style="color:var(--danger); text-align:center;">Error loading contracts: ${err.message}</td></tr>`;
    }
}

function queryForContract(vendorName) {
    document.querySelector('.tab-btn[data-tab="tab-assistant"]').click();
    const input = document.getElementById('query-input');
    input.value = `What are the payment terms and delivery SLAs for ${vendorName}?`;
    input.focus();
}

// Utility Helpers
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.innerText = text;
    return div.innerHTML;
}
