// src/components/InventoryTable.jsx
// Main inventory dashboard table with inline stock editing.

import { useState } from 'react';
import { updateItem } from '../api/client';

export default function InventoryTable({ items, onItemUpdated, addToast }) {
  return (
    <div className="card">
      <div className="card-body" style={{ padding: 0 }}>
        <table className="inventory-table">
          <thead>
            <tr>
              <th>Item</th>
              <th>Unit</th>
              <th>Stock</th>
              <th>Min Threshold</th>
              <th>Reorder Qty</th>
              <th>Supplier</th>
              <th>Status</th>
              <th>Update Stock</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr>
                <td colSpan={8}>
                  <div className="empty-state">
                    <div className="empty-icon">📋</div>
                    <p>No items yet. Add your first ingredient above.</p>
                  </div>
                </td>
              </tr>
            ) : (
              items.map((item) => (
                <InventoryRow
                  key={item.id}
                  item={item}
                  onUpdated={onItemUpdated}
                  addToast={addToast}
                />
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function InventoryRow({ item, onUpdated, addToast }) {
  const [stock, setStock] = useState(item.current_stock);
  const [loading, setLoading] = useState(false);
  const [dirty, setDirty] = useState(false);

  const handleChange = (e) => {
    setStock(e.target.value);
    setDirty(true);
  };

  const handleUpdate = async () => {
    const val = parseFloat(stock);
    if (isNaN(val) || val < 0) {
      addToast('Please enter a valid stock value', 'error');
      return;
    }
    setLoading(true);
    try {
      const updated = await updateItem(item.id, { current_stock: val });
      onUpdated(updated);
      setDirty(false);
      const wasLow = val <= item.minimum_threshold;
      if (wasLow) {
        addToast(`⚠️ ${item.item_name} is low — drafting restock email...`, 'info');
      } else {
        addToast(`${item.item_name} updated`, 'success');
      }
    } catch (err) {
      addToast(err.message, 'error');
    } finally {
      setLoading(false);
    }
  };

  const isLow = item.is_low_stock;

  return (
    <tr className={isLow ? 'low-stock-row' : ''}>
      <td className="item-name-cell">{item.item_name}</td>
      <td className="unit-cell">{item.unit}</td>
      <td>
        <strong style={{ color: isLow ? 'var(--red)' : 'var(--text-primary)' }}>
          {item.current_stock}
        </strong>
      </td>
      <td className="text-secondary">{item.minimum_threshold}</td>
      <td className="text-secondary">{item.reorder_quantity}</td>
      <td>
        <div className="supplier-cell">
          <div>{item.supplier_name}</div>
          <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>{item.supplier_email}</div>
        </div>
      </td>
      <td>
        <span className={`stock-badge ${isLow ? 'low' : 'ok'}`}>
          {isLow ? '● Low' : '● OK'}
        </span>
      </td>
      <td>
        <div className="stock-editor">
          <input
            type="number"
            step="0.1"
            min="0"
            className="stock-input"
            value={stock}
            onChange={handleChange}
            onKeyDown={(e) => e.key === 'Enter' && dirty && handleUpdate()}
          />
          <button
            className="btn btn-primary btn-sm"
            onClick={handleUpdate}
            disabled={loading || !dirty}
          >
            {loading ? <span className="spinner" /> : 'Set'}
          </button>
        </div>
      </td>
    </tr>
  );
}
