/**
 * Accessible tab strip: the one tablist/tab/tabpanel implementation in the
 * UI. Renders role="tablist" with roving-tabindex tabs, arrow-key (plus
 * Home/End) navigation with automatic activation, and a role="tabpanel"
 * for the active tab's content. Called by PageShell and TaskDetailPage.
 */
import { useId, useRef } from 'react';
import * as T from '../styles/tokens';

export interface TabDef {
  id: string;
  label: string;
  count?: number;
}

interface TabsProps {
  /** Tabs in display order. */
  tabs: TabDef[];
  /** Id of the currently active tab. */
  activeTab: string;
  /** Select a tab (click, Enter/Space, or arrow keys). */
  onTabChange: (tabId: string) => void;
  /** Accessible name for the tab strip, e.g. "Task views". */
  label: string;
  /** Content of the active tab, rendered inside role="tabpanel". */
  children: React.ReactNode;
  /** Styles for the tab strip row. */
  barStyle?: React.CSSProperties;
  /** Styles for one tab button given its active state. */
  tabStyle?: (active: boolean) => React.CSSProperties;
  /** Styles for the panel wrapper. */
  panelStyle?: React.CSSProperties;
}

// Shared default look: underline strip like the top NavBar active link.
const DEFAULT_BAR: React.CSSProperties = {
  display: 'flex',
  gap: 0,
  borderBottom: `1px solid ${T.colors.borderSubtle}`,
};

function defaultTab(active: boolean): React.CSSProperties {
  return {
    padding: '0.4rem 0.9rem',
    background: 'transparent',
    border: 'none',
    borderBottom: '2px solid transparent',
    borderBottomColor: active ? T.colors.accent : 'transparent',
    color: active ? T.colors.textPrimary : T.colors.textDim,
    fontSize: '0.8rem',
    fontWeight: active ? 600 : 500,
    cursor: 'pointer',
  };
}

const DEFAULT_PANEL: React.CSSProperties = {
  paddingTop: '0.875rem',
};

const COUNT: React.CSSProperties = {
  fontWeight: 400,
  color: T.colors.textDim,
  fontSize: '0.75rem',
  marginLeft: '0.375rem',
  fontVariantNumeric: 'tabular-nums',
};

// Keyboard-operable tab strip with arrow-key navigation.
export function Tabs({
  tabs,
  activeTab,
  onTabChange,
  label,
  children,
  barStyle,
  tabStyle,
  panelStyle,
}: TabsProps) {
  const baseId = useId().replace(/[^a-zA-Z0-9]/g, '');
  const listRef = useRef<HTMLDivElement>(null);

  // Focus the tab button for a tab id (used after arrow-key moves).
  function focusTab(tabId: string) {
    listRef.current
      ?.querySelector<HTMLElement>(`[data-tab-id="${tabId}"]`)
      ?.focus();
  }

  function move(fromId: string, delta: number) {
    const idx = tabs.findIndex((t) => t.id === fromId);
    if (idx === -1) return;
    const next = tabs[(idx + delta + tabs.length) % tabs.length];
    onTabChange(next.id);
    focusTab(next.id);
  }

  function handleKeyDown(e: React.KeyboardEvent, tabId: string) {
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
      e.preventDefault();
      move(tabId, 1);
    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
      e.preventDefault();
      move(tabId, -1);
    } else if (e.key === 'Home') {
      e.preventDefault();
      onTabChange(tabs[0].id);
      focusTab(tabs[0].id);
    } else if (e.key === 'End') {
      e.preventDefault();
      onTabChange(tabs[tabs.length - 1].id);
      focusTab(tabs[tabs.length - 1].id);
    }
  }

  return (
    <>
      <div ref={listRef} role="tablist" aria-label={label} style={barStyle ?? DEFAULT_BAR}>
        {tabs.map((tab) => {
          const active = tab.id === activeTab;
          return (
            <button
              key={tab.id}
              data-tab-id={tab.id}
              role="tab"
              id={`${baseId}-tab-${tab.id}`}
              aria-selected={active}
              aria-controls={`${baseId}-panel`}
              tabIndex={active ? 0 : -1}
              className="fleet-tab"
              style={tabStyle ? tabStyle(active) : defaultTab(active)}
              onClick={() => onTabChange(tab.id)}
              onKeyDown={(e) => handleKeyDown(e, tab.id)}
            >
              {tab.label}
              {tab.count != null && <span style={COUNT}>{tab.count}</span>}
            </button>
          );
        })}
      </div>
      <div
        role="tabpanel"
        id={`${baseId}-panel`}
        aria-labelledby={`${baseId}-tab-${activeTab}`}
        style={panelStyle ?? DEFAULT_PANEL}
      >
        {children}
      </div>
    </>
  );
}
