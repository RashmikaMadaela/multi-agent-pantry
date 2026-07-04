// src/App.jsx
// Root application component. Manages global state, polls for drafts,
// and orchestrates all child components.

import { useState, useEffect, useCallback, useRef } from 'react';
import { getInventory, getDrafts } from './api/client';
import InventoryTable from './components/InventoryTable';
import AddItemModal from './components/AddItemModal';
import DraftPanel from './components/DraftPanel';
import Toast from './components/Toast';

const POLL_INTERVAL_MS = 15_000; // Poll for new drafts every 15 seconds

let toastId = 0;

export default function App() {
  const [inventory, setInventory]     = useState([]);
  const [drafts, setDrafts]           = useState([]);
  const [toasts, setToasts]           = useState([]);
  const [showAddModal, setShowAddModal] = useState(false);
  const [showDraftPanel, setShowDraftPanel] = useState(false);
  const [loadingInv, setLoadingInv]   = useState(true);
  const prevDraftCountRef = useRef(0);

  const addToast = useCallback((message, type = 'info') => {
    const id = ++toastId;
    setToasts((t) => [...t, { id, message, type }]);
  }, []);

  const removeToast = useCallback((id) => {
    setToasts((t) => t.filter((x) => x.id !== id));
  }, []);

  // ── Load inventory on mount ──────────────────────────────────────────────
  useEffect(() => {
    getInventory()
      .then(setInventory)
      .catch(() => addToast('Could not load inventory. Is the API running?', 'error'))
      .finally(() => setLoadingInv(false));
  }, []);

  // ── Poll for pending drafts ──────────────────────────────────────────────
  const fetchDrafts = useCallback(async () => {
    try {
      const fresh = await getDrafts();
      setDrafts(fresh);

      // Notify user when a new draft arrives
      if (fresh.length > prevDraftCountRef.current && prevDraftCountRef.current >= 0) {
        const newCount = fresh.length - prevDraftCountRef.current;
        addToast(
          `🤖 ${newCount} restock email draft${newCount > 1 ? 's' : ''} ready to review!`,
          'info'
        );
      }
      prevDraftCountRef.current = fresh.length;
    } catch {
      // Silent fail — avoid toast spam on network blip
    }
  }, [addToast]);

  useEffect(() => {
    // Initial fetch, then poll
    fetchDrafts();
    const timer = setInterval(fetchDrafts, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [fetchDrafts]);

  // ── Derived stats ────────────────────────────────────────────────────────
  const totalItems  = inventory.length;
  const lowItems    = inventory.filter((i) => i.is_low_stock).length;
  const okItems     = totalItems - lowItems;
  const pendingDrafts = drafts.length;

  // ── Handlers ─────────────────────────────────────────────────────────────
  const handleItemAdded = (item) => {
    setInventory((prev) => [...prev, item].sort((a, b) => a.item_name.localeCompare(b.item_name)));
  };

  const handleItemUpdated = (updated) => {
    setInventory((prev) => prev.map((i) => (i.id === updated.id ? updated : i)));
    // Trigger a draft poll shortly after a stock update — the background task
    // may have completed by then
    setTimeout(fetchDrafts, 5000);
    setTimeout(fetchDrafts, 12000);
    setTimeout(fetchDrafts, 25000);
  };

  return (
    <div className="app-shell">
      {/* ── Topbar ─────────────────────────────────────────────────────── */}
      <header className="topbar">
        <div className="topbar-brand">
          <span className="brand-icon">🍽️</span>
          La Bella Cucina — Pantry Manager
        </div>

        <div className="topbar-actions">
          {/* Notification Bell */}
          <button
            id="notif-bell"
            className={`notif-btn ${pendingDrafts > 0 ? 'has-drafts' : ''}`}
            onClick={() => setShowDraftPanel(true)}
            title={pendingDrafts > 0 ? `${pendingDrafts} draft(s) ready` : 'No pending drafts'}
          >
            🔔
            {pendingDrafts > 0 && (
              <span className="notif-badge">{pendingDrafts}</span>
            )}
          </button>

          <button
            id="add-item-btn"
            className="btn btn-primary"
            onClick={() => setShowAddModal(true)}
          >
            + Add Item
          </button>
        </div>
      </header>

      {/* ── Main Content ────────────────────────────────────────────────── */}
      <main className="main-content">

        {/* Stats Row */}
        <div className="stats-row">
          <div className="stat-card">
            <span className="stat-label">Total Items</span>
            <span className="stat-value purple">{totalItems}</span>
          </div>
          <div className="stat-card">
            <span className="stat-label">Well Stocked</span>
            <span className="stat-value green">{okItems}</span>
          </div>
          <div className="stat-card">
            <span className="stat-label">Low Stock</span>
            <span className="stat-value red">{lowItems}</span>
          </div>
          <div className="stat-card">
            <span className="stat-label">Drafts Pending</span>
            <span className="stat-value amber">{pendingDrafts}</span>
          </div>
        </div>

        {/* Low stock alert banner */}
        {lowItems > 0 && (
          <div className="low-alert-banner">
            <span>⚠️</span>
            <span>
              <strong>{lowItems} item{lowItems > 1 ? 's are' : ' is'} running low.</strong>
              {' '}AI agents will automatically draft restock emails.
              {pendingDrafts > 0 && (
                <> — <button
                  style={{ background: 'none', border: 'none', color: 'inherit', textDecoration: 'underline', cursor: 'pointer', fontWeight: 700 }}
                  onClick={() => setShowDraftPanel(true)}
                >
                  {pendingDrafts} draft{pendingDrafts > 1 ? 's' : ''} ready to send
                </button></>
              )}
            </span>
          </div>
        )}

        {/* Inventory Table */}
        <div className="section-header">
          <h1 className="section-title">📦 Inventory</h1>
          <span className="text-muted">Updates auto-trigger restock emails when stock is low</span>
        </div>

        {loadingInv ? (
          <div className="empty-state">
            <div className="empty-icon"><span className="spinner" style={{ width: 40, height: 40, borderWidth: 3 }} /></div>
            <p>Loading inventory...</p>
          </div>
        ) : (
          <InventoryTable
            items={inventory}
            onItemUpdated={handleItemUpdated}
            addToast={addToast}
          />
        )}
      </main>

      {/* ── Modals & Panels ─────────────────────────────────────────────── */}
      {showAddModal && (
        <AddItemModal
          onClose={() => setShowAddModal(false)}
          onAdded={handleItemAdded}
          addToast={addToast}
        />
      )}

      {showDraftPanel && (
        <DraftPanel
          drafts={drafts}
          onClose={() => setShowDraftPanel(false)}
          onDraftsChange={(updated) => { setDrafts(updated); prevDraftCountRef.current = updated.length; }}
          addToast={addToast}
        />
      )}

      {/* ── Toasts ──────────────────────────────────────────────────────── */}
      <Toast toasts={toasts} removeToast={removeToast} />
    </div>
  );
}
