// src/components/AddItemModal.jsx
import { useState } from 'react';
import { addItem } from '../api/client';

const EMPTY = {
  item_name: '', unit: '', current_stock: '',
  minimum_threshold: '', reorder_quantity: '',
  supplier_name: '', supplier_email: '',
};

export default function AddItemModal({ onClose, onAdded, addToast }) {
  const [form, setForm] = useState(EMPTY);
  const [loading, setLoading] = useState(false);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const payload = {
        ...form,
        current_stock:     parseFloat(form.current_stock),
        minimum_threshold: parseFloat(form.minimum_threshold),
        reorder_quantity:  parseFloat(form.reorder_quantity),
      };
      const created = await addItem(payload);
      onAdded(created);
      addToast('Item added successfully!', 'success');
      onClose();
    } catch (err) {
      addToast(err.message, 'error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <h2>📦 Add Inventory Item</h2>
          <button className="draft-close-btn" onClick={onClose}>✕</button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            {/* Item details */}
            <div className="field-row">
              <div className="field">
                <label>Item Name</label>
                <input placeholder="e.g. Chicken Breast" value={form.item_name} onChange={set('item_name')} required />
              </div>
              <div className="field">
                <label>Unit</label>
                <input placeholder="kg / liters / units" value={form.unit} onChange={set('unit')} required />
              </div>
            </div>

            <div className="field-row">
              <div className="field">
                <label>Current Stock</label>
                <input type="number" step="0.1" min="0" placeholder="0.0" value={form.current_stock} onChange={set('current_stock')} required />
              </div>
              <div className="field">
                <label>Min Threshold</label>
                <input type="number" step="0.1" min="0.1" placeholder="0.0" value={form.minimum_threshold} onChange={set('minimum_threshold')} required />
              </div>
            </div>

            <div className="field">
              <label>Reorder Quantity</label>
              <input type="number" step="0.1" min="0.1" placeholder="Target stock after reorder" value={form.reorder_quantity} onChange={set('reorder_quantity')} required />
            </div>

            {/* Supplier details */}
            <hr style={{ border: 'none', borderTop: '1px solid var(--border)' }} />
            <div className="field">
              <label>Supplier Name</label>
              <input placeholder="e.g. Farm Fresh Meats" value={form.supplier_name} onChange={set('supplier_name')} required />
            </div>
            <div className="field">
              <label>Supplier Email</label>
              <input type="email" placeholder="orders@supplier.com" value={form.supplier_email} onChange={set('supplier_email')} required />
            </div>
          </div>

          <div className="modal-footer">
            <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={loading}>
              {loading ? <><span className="spinner" /> Adding...</> : '+ Add Item'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
