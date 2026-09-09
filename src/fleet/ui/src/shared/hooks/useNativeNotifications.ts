import { useCallback, useState } from 'react';
import { storageGet, storageSet } from '../storage';

type NotificationKind = 'ask_human' | 'completed';
type Permissions = Record<NotificationKind, boolean>;

const STORAGE_KEY = 'fleet_notif_prefs';

const DEFAULTS: Permissions = { ask_human: true, completed: true };

function load(): Permissions {
  const raw = storageGet(STORAGE_KEY);
  if (!raw) return { ...DEFAULTS };
  try {
    return { ...DEFAULTS, ...(JSON.parse(raw) as Partial<Permissions>) };
  } catch {
    return { ...DEFAULTS };
  }
}

function save(perms: Permissions): void {
  storageSet(STORAGE_KEY, JSON.stringify(perms));
}

function fireNotification(title: string, body: string): void {
  try {
    new Notification(title, { body });
  } catch {
    // ignore
  }
}

export function useNativeNotifications(): {
  notify: (kind: NotificationKind, title: string, body: string) => void;
  permissions: Permissions;
  setPermission: (kind: NotificationKind, enabled: boolean) => void;
} {
  const [permissions, setPermissionsState] = useState<Permissions>(load);

  const notify = useCallback((kind: NotificationKind, title: string, body: string) => {
    // Read directly from localStorage so this is always current regardless of which instance
    if (!load()[kind]) return;

    if (Notification.permission === 'granted') {
      fireNotification(title, body);
    } else if (Notification.permission !== 'denied') {
      void Notification.requestPermission().then(result => {
        if (result === 'granted') fireNotification(title, body);
      });
    }
  }, []);

  const setPermission = useCallback((kind: NotificationKind, enabled: boolean) => {
    setPermissionsState(prev => {
      const next: Permissions = { ...prev, [kind]: enabled };
      save(next);
      return next;
    });
  }, []);

  return { notify, permissions, setPermission };
}
