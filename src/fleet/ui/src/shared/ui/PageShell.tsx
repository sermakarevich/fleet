// Shared page wrapper: heading with count, optional subtitle,
// right-side actions slot and an optional sub-tab bar (shared Tabs).
// Rendered by every page so headings, counts and tab strips look alike.
import type { ReactNode } from 'react';
import { useIsMobile } from '../hooks/useIsMobile';
import * as T from '../styles/tokens';
import * as R from '../styles/recipes';
import { Tabs, type TabDef } from './Tabs';

interface PageShellProps {
  title: string;
  count?: number;
  subtitle?: ReactNode;
  /** Right-side buttons (e.g. "+ New schedule"). */
  actions?: ReactNode;
  /** Sub-tabs rendered under the heading (uses shared Tabs). */
  tabs?: TabDef[];
  activeTab?: string;
  onTabChange?: (tabId: string) => void;
  children: ReactNode;
}

export function PageShell({
  title,
  count,
  subtitle,
  actions,
  tabs,
  activeTab,
  onTabChange,
  children,
}: PageShellProps) {
  const isMobile = useIsMobile();
  return (
    <div style={R.pageStyle(isMobile)}>
      <div style={R.topBarStyle()}>
        <h1 style={R.headingStyle()}>
          {title}
          {count != null && <span style={R.countStyle()}> ({count})</span>}
        </h1>
        {subtitle && <span style={R.mutedStyle()}>{subtitle}</span>}
        {actions && <span style={styles.actions}>{actions}</span>}
      </div>
      {tabs && activeTab && onTabChange ? (
        <Tabs
          tabs={tabs}
          activeTab={activeTab}
          onTabChange={onTabChange}
          label={`${title} views`}
        >
          {children}
        </Tabs>
      ) : (
        children
      )}
    </div>
  );
}

const styles = {
  actions: {
    marginLeft: 'auto', display: 'inline-flex', gap: '0.5rem',
    alignItems: 'center', color: T.colors.textPrimary,
  } as React.CSSProperties,
};
