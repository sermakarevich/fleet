/**
 * Schedules browser: list of recurring workers, create/edit form and a
 * detail drawer with upcoming firings and run history.
 * Called by App's /schedules and /schedules/:id routes; the selected id
 * and the create form live in the URL so both are shareable.
 */
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useSchedules } from '../../shared/hooks/useApi';
import { useIsMobile } from '../../shared/hooks/useIsMobile';
import * as T from '../../shared/styles/tokens';
import * as R from '../../shared/styles/recipes';
import { SchedulesTable } from './SchedulesTable';
import { ScheduleDrawer } from './ScheduleDrawer';
import { ScheduleForm } from './ScheduleForm';

// Schedules page: heading, table, create form and detail drawer.
export function SchedulesPage() {
  const { data: schedules, isLoading, error } = useSchedules();
  const isMobile = useIsMobile();
  const navigate = useNavigate();
  const { id: selectedId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const showCreate = searchParams.get('new') === '1';

  if (isLoading) {
    return <p style={R.msgStyle()}>Loading…</p>;
  }
  if (error) {
    return <p style={R.errorMsgStyle()}>Error: {String(error)}</p>;
  }

  const items = schedules ?? [];

  return (
    <div style={R.pageStyle(isMobile)}>
      <div style={R.topBarStyle()}>
        <h2 style={R.headingStyle()}>
          Schedules <span style={R.countStyle()}>({items.length})</span>
        </h2>
        <button
          style={R.merge(T.btnPrimary, { marginLeft: 'auto' })}
          onClick={() => setSearchParams({ new: '1' })}
        >
          + New schedule
        </button>
      </div>
      <SchedulesTable
        items={items}
        selectedId={selectedId ?? null}
        onSelect={(id) => navigate(`/schedules/${id}`)}
        isMobile={isMobile}
      />
      {selectedId && <ScheduleDrawer scheduleId={selectedId} onClose={() => navigate('/schedules')} />}
      {showCreate && (
        <ScheduleForm
          onClose={() => navigate(selectedId ? `/schedules/${selectedId}` : '/schedules')}
          onSaved={(saved) => navigate(`/schedules/${saved.id}`)}
        />
      )}
    </div>
  );
}
