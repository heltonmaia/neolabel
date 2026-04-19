import { useCallback, useEffect, useState } from 'react';

type Tone = 'default' | 'danger';

export type ConfirmOptions = {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: Tone;
  onConfirm: () => void;
};

type OpenState = Required<ConfirmOptions>;

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

  const ask = useCallback((o: ConfirmOptions) => setState(normalize(o)), []);
  const close = useCallback(() => setState(null), []);

  useEffect(() => {
    if (!state) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') close();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [state, close]);

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
        <div className="p-5 space-y-2">
          <h2 id="confirm-title" className="text-base font-semibold text-slate-900">
            {state.title}
          </h2>
          <p className="text-sm text-slate-600 leading-relaxed whitespace-pre-line">
            {state.message}
          </p>
        </div>
        <div className="flex items-center justify-end gap-2 px-4 py-3 bg-slate-50 border-t border-slate-200">
          <button
            type="button"
            onClick={close}
            className="px-3 py-1.5 rounded-lg text-sm font-medium text-slate-700 bg-white border border-slate-200 hover:bg-slate-100 hover:border-slate-300 active:translate-y-px transition"
          >
            {state.cancelLabel}
          </button>
          <button
            type="button"
            autoFocus
            onClick={() => {
              const fn = state.onConfirm;
              close();
              fn();
            }}
            className={
              'px-3 py-1.5 rounded-lg text-sm font-semibold text-white shadow-sm active:translate-y-px transition '
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
