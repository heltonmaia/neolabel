import { useCallback, useEffect, useRef, useState } from 'react';

type Tone = 'default' | 'danger';

export type ConfirmOptions = {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: Tone;
  /** When set, the user must type this exact string to enable the Confirm
   * button. Use for high-stakes destructive operations (delete project,
   * delete video) where a single click would be too easy to slip on. */
  requireTypedConfirmation?: string;
  onConfirm: () => void;
};

type OpenState = ConfirmOptions & {
  confirmLabel: string;
  cancelLabel: string;
  tone: Tone;
};

function normalize(o: ConfirmOptions): OpenState {
  return {
    confirmLabel: 'Confirm',
    cancelLabel: 'Cancel',
    tone: 'default',
    ...o,
  };
}

export function useConfirm() {
  const [state, setState] = useState<OpenState | null>(null);
  const [typedInput, setTypedInput] = useState('');
  const cancelRef = useRef<HTMLButtonElement | null>(null);

  const ask = useCallback((o: ConfirmOptions) => {
    setTypedInput('');
    setState(normalize(o));
  }, []);
  const close = useCallback(() => setState(null), []);

  useEffect(() => {
    if (!state) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') close();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [state, close]);

  const typedOk =
    !state?.requireTypedConfirmation
    || typedInput === state.requireTypedConfirmation;
  const confirmDisabled = !typedOk;

  const dialog = state ? (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-sm p-4"
      onClick={close}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-sm bg-white rounded-xl shadow-2xl ring-1 ring-slate-200 overflow-hidden"
      >
        <div className="p-5 space-y-3">
          <h2 id="confirm-title" className="text-base font-semibold text-slate-900">
            {state.title}
          </h2>
          <p className="text-sm text-slate-600 leading-relaxed whitespace-pre-line">
            {state.message}
          </p>
          {state.requireTypedConfirmation && (
            <div className="space-y-1 pt-1">
              <label className="block text-xs text-slate-600">
                Type{' '}
                <code className="px-1 py-0.5 rounded bg-slate-100 text-slate-800 font-mono">
                  {state.requireTypedConfirmation}
                </code>{' '}
                to confirm:
              </label>
              <input
                type="text"
                value={typedInput}
                onChange={(e) => setTypedInput(e.target.value)}
                autoFocus
                autoComplete="off"
                spellCheck={false}
                className="w-full border border-slate-300 rounded px-2 py-1.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-red-300"
              />
            </div>
          )}
        </div>
        <div className="flex items-center justify-end gap-2 px-4 py-3 bg-slate-50 border-t border-slate-200">
          <button
            ref={cancelRef}
            type="button"
            onClick={close}
            // For danger tone we focus Cancel by default — Enter from a
            // reflex keystroke shouldn't trigger an irreversible action.
            // The typed-confirmation case auto-focuses the input instead,
            // so we only autoFocus Cancel when there's no input field.
            autoFocus={state.tone === 'danger' && !state.requireTypedConfirmation}
            className="px-3 py-1.5 rounded-lg text-sm font-medium text-slate-700 bg-white border border-slate-200 hover:bg-slate-100 hover:border-slate-300 active:translate-y-px transition"
          >
            {state.cancelLabel}
          </button>
          <button
            type="button"
            disabled={confirmDisabled}
            // Keep autoFocus on Confirm only for non-danger dialogs (e.g.
            // 'Copy previous pose'), where speed matters more than safety.
            autoFocus={state.tone !== 'danger' && !state.requireTypedConfirmation}
            onClick={() => {
              const fn = state.onConfirm;
              close();
              fn();
            }}
            className={
              'px-3 py-1.5 rounded-lg text-sm font-semibold text-white shadow-sm active:translate-y-px transition disabled:opacity-40 disabled:cursor-not-allowed '
              + (state.tone === 'danger'
                ? 'bg-red-600 hover:bg-red-700'
                : 'bg-slate-900 hover:bg-slate-800')
            }
          >
            {state.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  ) : null;

  return { ask, dialog, isOpen: !!state };
}
