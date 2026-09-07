import { useCallback, useEffect, useState } from 'react';

export function useCommandPalette(): { open: boolean; setOpen: (v: boolean) => void } {
  const [open, setOpenState] = useState(false);
  const setOpen = useCallback((v: boolean) => setOpenState(v), []);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setOpen(true);
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [setOpen]);

  return { open, setOpen };
}
