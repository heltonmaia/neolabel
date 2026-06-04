interface Props {
  inFlight: boolean;
  disabled?: boolean;
  onRotate: (degrees: 90 | 180 | 270) => void;
}

/** Three small per-video rotation controls: 90° CW, 90° CCW, 180°. */
export function VideoRotateButtons({ inFlight, disabled, onRotate }: Props) {
  const cls = 'p-1 text-slate-400 hover:text-slate-700 disabled:opacity-40 leading-none';
  const off = inFlight || disabled;
  return (
    <span className="inline-flex items-center">
      <button type="button" disabled={off} onClick={() => onRotate(90)}
        className={cls} title="Rotate 90° clockwise"
        aria-label="Rotate 90 degrees clockwise">↻</button>
      <button type="button" disabled={off} onClick={() => onRotate(270)}
        className={cls} title="Rotate 90° counter-clockwise"
        aria-label="Rotate 90 degrees counter-clockwise">↺</button>
      <button type="button" disabled={off} onClick={() => onRotate(180)}
        className={cls} title="Rotate 180°"
        aria-label="Rotate 180 degrees">⟳</button>
    </span>
  );
}
