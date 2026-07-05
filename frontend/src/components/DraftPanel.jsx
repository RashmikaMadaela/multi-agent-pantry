// src/components/DraftPanel.jsx
// Slide-up panel showing pending email drafts.
// Each draft is supplier-scoped and may cover multiple low-stock items.

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
      const result = await sendDraft(draft.id);
      const remaining = localDrafts.filter((d) => d.id !== draft.id);
      setLocalDrafts(remaining);
      onDraftsChange(remaining);
      const itemCount = draft.items?.length ?? 1;
      addToast(
        `📧 Email sent to ${draft.supplier_email}! (${itemCount} item${itemCount !== 1 ? 's' : ''} requested)`,
        'success'
      );
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
  const items = draft.items ?? [];

  return (
    <div className="draft-item">
      <div className="draft-item-meta">
        {/* Supplier heading */}
        <div className="draft-item-supplier" style={{ marginBottom: '8px' }}>
          <span>📬</span>
          <strong>{draft.supplier_name}</strong>
          <span style={{ color: 'var(--text-muted)' }}>({draft.supplier_email})</span>
        </div>

        {/* Items covered by this draft */}
        {items.length > 0 && (
          <div className="draft-items-list">
            <div className="draft-items-label">
              ⚠️ {items.length} low-stock item{items.length !== 1 ? 's' : ''} in this order:
            </div>
            <ul className="draft-items-ul">
              {items.map((item) => (
                <li key={item.item_id} className="draft-items-li">
                  <span className="draft-item-name">{item.item_name}</span>
                  <span className="draft-item-qty">
                    {item.current_stock} / {item.reorder_quantity} {item.unit}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
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
