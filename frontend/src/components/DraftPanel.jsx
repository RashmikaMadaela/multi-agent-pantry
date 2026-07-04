// src/components/DraftPanel.jsx
// Slide-up panel showing pending email drafts.
// Each draft is editable and can be sent with one click.

import { useState } from 'react';
import { updateDraft, sendDraft, dismissDraft } from '../api/client';

export default function DraftPanel({ drafts, onClose, onDraftsChange, addToast }) {
  const [localDrafts, setLocalDrafts] = useState(drafts);
  const [sending, setSending] = useState({});
  const [saving, setSaving] = useState({});

  const updateLocal = (id, fields) =>
    setLocalDrafts((ds) => ds.map((d) => (d.id === id ? { ...d, ...fields } : d)));

  const handleSave = async (draft) => {
    setSaving((s) => ({ ...s, [draft.id]: true }));
    try {
      await updateDraft(draft.id, { draft_text: draft.draft_text, subject: draft.subject });
      addToast('Draft saved', 'success');
    } catch (err) {
      addToast(err.message, 'error');
    } finally {
      setSaving((s) => ({ ...s, [draft.id]: false }));
    }
  };

  const handleSend = async (draft) => {
    setSending((s) => ({ ...s, [draft.id]: true }));
    try {
      // Save latest edits first
      await updateDraft(draft.id, { draft_text: draft.draft_text, subject: draft.subject });
      await sendDraft(draft.id);
      const remaining = localDrafts.filter((d) => d.id !== draft.id);
      setLocalDrafts(remaining);
      onDraftsChange(remaining);
      addToast(`📧 Email sent to ${draft.supplier_email}!`, 'success');
      if (remaining.length === 0) onClose();
    } catch (err) {
      addToast(err.message, 'error');
    } finally {
      setSending((s) => ({ ...s, [draft.id]: false }));
    }
  };

  const handleDismiss = async (id) => {
    try {
      await dismissDraft(id);
      const remaining = localDrafts.filter((d) => d.id !== id);
      setLocalDrafts(remaining);
      onDraftsChange(remaining);
      addToast('Draft dismissed', 'info');
      if (remaining.length === 0) onClose();
    } catch (err) {
      addToast(err.message, 'error');
    }
  };

  return (
    <div className="draft-panel-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="draft-panel">
        <div className="draft-panel-header">
          <h2>✉️ Restock Email Drafts</h2>
          <button className="draft-close-btn" onClick={onClose}>✕</button>
        </div>

        <div className="draft-list">
          {localDrafts.length === 0 ? (
            <div className="empty-state">
              <div className="empty-icon">🎉</div>
              <p>All caught up! No pending drafts.</p>
            </div>
          ) : (
            localDrafts.map((draft) => (
              <DraftCard
                key={draft.id}
                draft={draft}
                onChange={(fields) => updateLocal(draft.id, fields)}
                onSave={() => handleSave(draft)}
                onSend={() => handleSend(draft)}
                onDismiss={() => handleDismiss(draft.id)}
                isSending={!!sending[draft.id]}
                isSaving={!!saving[draft.id]}
              />
            ))
          )}
        </div>
      </div>
    </div>
  );
}

function DraftCard({ draft, onChange, onSave, onSend, onDismiss, isSending, isSaving }) {
  return (
    <div className="draft-item">
      <div className="draft-item-meta">
        <div className="draft-item-title">⚠️ {draft.item_name} — Low Stock</div>
        <div className="draft-item-supplier">
          <span>📬</span>
          <strong>{draft.supplier_name}</strong>
          <span style={{ color: 'var(--text-muted)' }}>({draft.supplier_email})</span>
        </div>
      </div>

      <div className="field">
        <label>Subject</label>
        <input
          className="draft-subject-input"
          value={draft.subject}
          onChange={(e) => onChange({ subject: e.target.value })}
        />
      </div>

      <div className="field">
        <label>Email Body — edit before sending</label>
        <textarea
          className="draft-textarea"
          value={draft.draft_text}
          onChange={(e) => onChange({ draft_text: e.target.value })}
        />
      </div>

      <div className="draft-actions">
        <button className="btn btn-success" onClick={onSend} disabled={isSending} style={{ flex: 1 }}>
          {isSending
            ? <><span className="spinner" /> Sending...</>
            : '📤 Send to Supplier'}
        </button>
        <button className="btn btn-ghost btn-sm" onClick={onSave} disabled={isSaving}>
          {isSaving ? '...' : '💾'}
        </button>
        <button className="btn btn-danger btn-sm" onClick={onDismiss} disabled={isSending}>
          🗑️
        </button>
      </div>
    </div>
  );
}
