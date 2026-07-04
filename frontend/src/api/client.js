// src/api/client.js
// Centralised API client — all fetch calls go through here.

const BASE = 'http://localhost:8000';

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Request failed');
  }
  return res.json();
}

// ── Inventory ──────────────────────────────────────────────────────────────
export const getInventory = () => request('/api/inventory');

export const addItem = (data) =>
  request('/api/inventory', { method: 'POST', body: JSON.stringify(data) });

export const updateItem = (id, data) =>
  request(`/api/inventory/${id}`, { method: 'PUT', body: JSON.stringify(data) });

// ── Drafts ─────────────────────────────────────────────────────────────────
export const getDrafts = () => request('/api/drafts');

export const updateDraft = (id, data) =>
  request(`/api/drafts/${id}`, { method: 'PUT', body: JSON.stringify(data) });

export const sendDraft = (id) =>
  request(`/api/drafts/${id}/send`, { method: 'POST' });

export const dismissDraft = (id) =>
  request(`/api/drafts/${id}`, { method: 'DELETE' });
