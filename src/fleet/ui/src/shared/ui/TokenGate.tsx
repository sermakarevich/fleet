/**
 * API-token gate: a modal with a token field shown after a 401.
 * Called by App; replaces the old window.prompt inside shared/api.ts.
 * The token is stored in localStorage and every query is invalidated
 * so requests retry with the new token.
 */
import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { onAuthRequired, setFleetToken } from '../api';

export function TokenGate() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [token, setToken] = useState('');

  useEffect(() => onAuthRequired(() => setOpen(true)), []);

  if (!open) return null;

  function save() {
    if (!token.trim()) return;
    setFleetToken(token.trim());
    setToken('');
    setOpen(false);
    void qc.invalidateQueries();
  }

  return (
    <div style={styles.backdrop}>
      <div style={styles.panel}>
        <h2 style={styles.title}>Fleet API token required</h2>
        <p style={styles.hint}>The server rejected the request (401). Paste the token to retry.</p>
        <input
          type="password"
          autoFocus
          style={styles.input}
          placeholder="API token"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') save();
            if (e.key === 'Escape') setOpen(false);
          }}
        />
        <div style={styles.actions}>
          <button style={styles.cancelBtn} onClick={() => setOpen(false)}>
            Later
          </button>
          <button style={styles.saveBtn} onClick={save} disabled={!token.trim()}>
            Save token
          </button>
        </div>
      </div>
    </div>
  );
}

const styles = {
  backdrop: {
    position: 'fixed' as const,
    inset: 0,
    background: 'rgba(0,0,0,0.55)',
    zIndex: 3000,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
  panel: {
    width: 380,
    background: '#18181b',
    border: '1px solid #3f3f46',
    borderRadius: 8,
    padding: '1.25rem',
    fontFamily: 'system-ui, sans-serif',
  },
  title: {
    margin: '0 0 0.5rem',
    fontSize: '0.9375rem',
    fontWeight: 600,
    color: '#e4e4e7',
  },
  hint: {
    margin: '0 0 0.75rem',
    fontSize: '0.8125rem',
    color: '#a1a1aa',
  },
  input: {
    width: '100%',
    boxSizing: 'border-box' as const,
    background: '#09090b',
    border: '1px solid #3f3f46',
    borderRadius: 4,
    color: '#e4e4e7',
    padding: '0.5rem 0.625rem',
    fontSize: '0.875rem',
    outline: 'none',
  },
  actions: {
    display: 'flex',
    justifyContent: 'flex-end',
    gap: '0.5rem',
    marginTop: '0.875rem',
  },
  cancelBtn: {
    padding: '0.35rem 0.875rem',
    background: 'transparent',
    border: '1px solid #3f3f46',
    borderRadius: 4,
    color: '#a1a1aa',
    cursor: 'pointer',
    fontSize: '0.8125rem',
  },
  saveBtn: {
    padding: '0.35rem 0.875rem',
    background: '#1d4ed8',
    border: '1px solid #1d4ed8',
    borderRadius: 4,
    color: '#fff',
    cursor: 'pointer',
    fontSize: '0.8125rem',
  },
};
