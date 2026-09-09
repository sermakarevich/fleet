/**
 * Websocket overlays for the tasks list: per-task patches from /ws/events
 * (last event kind, idle reset, token count). Called by RunsTab (workers page), which
 * derives the displayed list from the polled query plus these overlays in
 * a useMemo so polls never discard updates that arrived between polls.
 */
import { useCallback, useState } from 'react';
import type { FleetEvent, TaskSummary } from '../types';

export type TaskOverlay = Partial<TaskSummary>;

function overlayFromEvent(event: FleetEvent): TaskOverlay {
  const overlay: TaskOverlay = {
    last_event_kind: event.kind,
    last_event_detail: event.tool_name,
    idle_sec: 0,
  };
  if (event.usage != null) {
    const input = event.usage.input_tokens ?? 0;
    const cacheRead = event.usage.cache_read_input_tokens ?? 0;
    const cacheCreate = event.usage.cache_creation_input_tokens ?? 0;
    overlay.context_tokens = input + cacheRead + cacheCreate;
  }
  return overlay;
}

/** Live patches keyed by task id, plus the event handler that writes them. */
export function useTasksState() {
  const [overlays, setOverlays] = useState<Record<string, TaskOverlay>>({});

  const updateFromEvent = useCallback((taskId: string, event: FleetEvent) => {
    setOverlays((prev) => ({ ...prev, [taskId]: overlayFromEvent(event) }));
  }, []);

  return { overlays, updateFromEvent };
}

/** Polled tasks with the live socket overlays applied (pure, for useMemo). */
export function applyTaskOverlays(tasks: TaskSummary[], overlays: Record<string, TaskOverlay>): TaskSummary[] {
  if (Object.keys(overlays).length === 0) return tasks;
  return tasks.map((task) => {
    const overlay = overlays[task.id];
    return overlay ? { ...task, ...overlay } : task;
  });
}
