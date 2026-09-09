/**
 * The one factory behind every UI mutation: runs the API call,
 * invalidates query keys, and toasts the outcome — failures always
 * toast, so no failed action is ever silent. Called by every mutation
 * hook in useApi.ts and features/chat/hooks/useChat.ts.
 */
import { useMutation, useQueryClient, type QueryKey, type UseMutationResult } from '@tanstack/react-query';
import { errorMessage } from '../api';
import { useToast } from '../contexts/ToastContext';

export interface TaskMutationOptions<TData, TVars> {
  /** Query keys to invalidate on success (or a function of result + vars). */
  invalidate?: QueryKey[] | ((data: TData, vars: TVars) => QueryKey[]);
  /** Success toast, or a function of the result; null/undefined toasts nothing. */
  success?: string | ((data: TData, vars: TVars) => string | null | undefined);
  /** Failure toast; defaults to "… failed: <error>". */
  failure?: string | ((vars: TVars, err: unknown) => string);
}

function resolveSuccess<TData, TVars>(
  success: TaskMutationOptions<TData, TVars>['success'],
  data: TData,
  vars: TVars,
): string | null {
  if (success === undefined) return null;
  const text = typeof success === 'function' ? success(data, vars) : success;
  return text ?? null;
}

function resolveFailure<TData, TVars>(
  failure: TaskMutationOptions<TData, TVars>['failure'],
  action: string,
  vars: TVars,
  err: unknown,
): string {
  if (failure === undefined) return `${action} failed: ${errorMessage(err)}`;
  return typeof failure === 'function' ? failure(vars, err) : failure;
}

/**
 * Build a mutation that invalidates keys and toasts success/failure.
 * Action names the operation for the default failure toast ("Kill task").
 */
export function useTaskMutation<TData>(
  action: string,
  fn: () => Promise<TData>,
  options?: TaskMutationOptions<TData, void>,
): UseMutationResult<TData, Error, void>;
export function useTaskMutation<TData, TVars>(
  action: string,
  fn: (vars: TVars) => Promise<TData>,
  options?: TaskMutationOptions<TData, TVars>,
): UseMutationResult<TData, Error, TVars>;
export function useTaskMutation<TData, TVars>(
  action: string,
  fn: (vars: TVars) => Promise<TData>,
  options: TaskMutationOptions<TData, TVars> = {},
) {
  const qc = useQueryClient();
  const { addToast } = useToast();
  return useMutation({
    mutationFn: fn,
    onSuccess: (data, vars) => {
      const keys = typeof options.invalidate === 'function'
        ? options.invalidate(data, vars)
        : (options.invalidate ?? []);
      for (const key of keys) {
        void qc.invalidateQueries({ queryKey: key });
      }
      const text = resolveSuccess(options.success, data, vars);
      if (text) addToast(text);
    },
    onError: (err, vars) => {
      addToast(resolveFailure(options.failure, action, vars, err));
    },
  });
}
