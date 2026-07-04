// src/components/Toast.jsx
import { useEffect } from 'react';

export default function Toast({ toasts, removeToast }) {
  return (
    <div className="toast-container">
      {toasts.map((t) => (
        <ToastItem key={t.id} toast={t} onRemove={() => removeToast(t.id)} />
      ))}
    </div>
  );
}

function ToastItem({ toast, onRemove }) {
  useEffect(() => {
    const timer = setTimeout(onRemove, 3500);
    return () => clearTimeout(timer);
  }, []);

  const icons = { success: '✅', error: '❌', info: 'ℹ️' };
  return (
    <div className={`toast ${toast.type}`}>
      <span>{icons[toast.type] || '💬'}</span>
      {toast.message}
    </div>
  );
}
