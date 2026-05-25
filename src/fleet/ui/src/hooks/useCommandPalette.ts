import { useCallback, useState } from 'react';

export function useCommandPalette(): { open: boolean; setOpen: (v: boolean) => void } {
  const [open, setOpenState] = useState(false);
  const setOpen = useCallback((v: boolean) => setOpenState(v), []);
  return { open, setOpen };
}
