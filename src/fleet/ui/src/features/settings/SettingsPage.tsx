// Settings page (ADR 0009): every RuntimeConfig field grouped into
// sections with one Save per section, coder/model dropdowns from
// useCoders(), restart badges from restart_required, and the read-only
// constants table. Route /settings; /config redirects here.
import { useCoders, useConfig } from '../../shared/hooks/useApi';
import { useIsMobile } from '../../shared/hooks/useIsMobile';
import * as T from '../../shared/styles/tokens';
import { LoadingState } from '../../shared/ui/LoadingState';
import { PageShell } from '../../shared/ui/PageShell';
import { CodersList } from './CodersList';
import { ConfigSection } from './ConfigSection';
import { ConstantsSection } from './ConstantsSection';
import { NotificationsSection } from './NotificationsSection';
import { SECTIONS, type SectionId } from './settingsSections';
import { SupervisorSection } from './SupervisorSection';
import { useSettingsForm } from './useSettingsForm';

const EDITABLE: SectionId[] = [
  'concurrency',
  'coders-models',
  'worker-limits',
  'isolation-merge',
  'triage',
  'jobs',
  'compaction',
  'housekeeping',
  'integrations',
  'server',
];

export function SettingsPage() {
  const { data: config, isLoading: configLoading } = useConfig();
  const { data: codersData, isLoading: codersLoading } = useCoders();
  const isMobile = useIsMobile();
  const form = useSettingsForm(config);

  if (configLoading || codersLoading || !config || !form.draft) return <LoadingState />;

  const coders = codersData?.coders ?? [];
  const restartFields = new Set(config.restart_required ?? []);
  const { draft } = form;
  if (!draft) return <LoadingState />;

  return (
    <PageShell title="Settings" subtitle="Every runtime setting, grouped. Most hot-reload; marked server fields need a restart.">
      <div style={isMobile ? styles.bodyMobile : styles.body}>
        <nav aria-label="Settings groups" style={isMobile ? styles.navMobile : styles.nav}>
          {SECTIONS.map(s => (
            <a key={s.id} href={`#settings-${s.id}`} style={styles.navLink}>
              {s.title}
            </a>
          ))}
        </nav>
        <div style={styles.sections}>
          <SupervisorSection />
          {EDITABLE.map(section => (
            <div key={section}>
              <ConfigSection
                section={section}
                draft={draft}
                setField={form.setField}
                dirty={form.isDirty(section)}
                isFieldDirty={form.isFieldDirty}
                saving={form.saving}
                error={form.sectionErrors[section]}
                coders={coders}
                restartFields={restartFields}
                onSave={() => void form.saveSection(section)}
              />
              {section === 'coders-models' && <CodersList coders={coders} />}
            </div>
          ))}
          <NotificationsSection />
          <ConstantsSection />
        </div>
      </div>
    </PageShell>
  );
}

const styles = {
  body: {
    display: 'flex',
    gap: '1.5rem',
    alignItems: 'flex-start',
  } as React.CSSProperties,
  bodyMobile: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '1rem',
  } as React.CSSProperties,
  nav: {
    position: 'sticky' as const,
    top: '3.5rem',
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '0.125rem',
    minWidth: '11rem',
    flexShrink: 0,
  } as React.CSSProperties,
  navMobile: {
    display: 'flex',
    flexDirection: 'row' as const,
    flexWrap: 'wrap' as const,
    gap: '0.375rem',
  } as React.CSSProperties,
  navLink: {
    color: T.colors.textSecondary,
    textDecoration: 'none',
    fontSize: '0.8125rem',
    padding: '0.3rem 0.625rem',
    borderRadius: '0.25rem',
  } as React.CSSProperties,
  sections: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '1rem',
    flex: 1,
    minWidth: 0,
  } as React.CSSProperties,
};
