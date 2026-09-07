import { createContext, useContext, useState, type ReactNode } from 'react';

interface ToastContextType {
  addToast: (message: string) => void;
}

export const ToastContext = createContext<ToastContextType>({ addToast: () => {} });

export function useToast(): ToastContextType {
  return useContext(ToastContext);
}

interface Toast {
  id: string;
  message: string;
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    position: 'fixed',
    bottom: '1.5rem',
    right: '1.5rem',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.5rem',
    zIndex: 1000,
  },
  toast: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.75rem',
    background: '#1d4ed8',
    color: '#fff',
    padding: '0.75rem 1rem',
    borderRadius: 6,
    boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
    maxWidth: '20rem',
    fontSize: '0.875rem',
    fontFamily: 'system-ui, sans-serif',
  },
  text: {
    flex: 1,
  },
  close: {
    background: 'none',
    border: 'none',
    color: '#93c5fd',
    cursor: 'pointer',
    fontSize: '1.125rem',
    lineHeight: 1,
    padding: 0,
    flexShrink: 0,
  },
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const addToast = (message: string) => {
    const id = String(Date.now());
    setToasts(prev => [...prev, { id, message }]);
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 6000);
  };

  const dismiss = (id: string) => setToasts(prev => prev.filter(t => t.id !== id));

  return (
    <ToastContext.Provider value={{ addToast }}>
      {children}
      {toasts.length > 0 && (
        <div style={styles.container}>
          {toasts.map(t => (
            <div key={t.id} style={styles.toast}>
              <span style={styles.text}>{t.message}</span>
              <button style={styles.close} onClick={() => dismiss(t.id)}>×</button>
            </div>
          ))}
        </div>
      )}
    </ToastContext.Provider>
  );
}
