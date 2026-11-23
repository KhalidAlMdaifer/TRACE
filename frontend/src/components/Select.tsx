// A drop-down in the app's own colours. A native <select> draws its list with the system's
// light menu, which the dark theme cannot reach.
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

interface Props { label: string; value: string | undefined; options: { id: string; name: string }[]; onChange: (id: string) => void; disabled?: boolean; className?: string }

export function Select({ label, value, options, onChange, disabled = false, className = "" }: Props) {
  const id = useId();
  const box = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const chosen = Math.max(0, options.findIndex((o) => o.id === value));
  const [at, setAt] = useState(chosen);

  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);
  useEffect(() => { if (disabled) setOpen(false); }, [disabled]);

  const show = () => { setAt(chosen); setOpen(true); };
  const choose = (i: number) => { setOpen(false); if (options[i] && options[i].id !== value) onChange(options[i].id); };
  const onKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    const move = e.key === "ArrowDown" ? 1 : e.key === "ArrowUp" ? -1 : 0;
    if (move) { e.preventDefault(); if (open) setAt((at + move + options.length) % options.length); else show(); }
    else if (e.key === "Home" && open) { e.preventDefault(); setAt(0); }
    else if (e.key === "End" && open) { e.preventDefault(); setAt(options.length - 1); }
    else if ((e.key === "Enter" || e.key === " ") && open) { e.preventDefault(); choose(at); }
    else if (e.key === "Escape" && open) { e.preventDefault(); e.stopPropagation(); setOpen(false); }
    else if (e.key === "Tab") setOpen(false);
  };

  return (
    <div ref={box} className={`select mono11 ${className}`}>
      <span id={`${id}-label`}>{label}</span>
      <button type="button" role="combobox" aria-haspopup="listbox" aria-expanded={open} aria-controls={`${id}-list`}
              aria-labelledby={`${id}-label ${id}-value`} aria-activedescendant={open ? `${id}-${at}` : undefined}
              disabled={disabled} onClick={() => (open ? setOpen(false) : show())} onKeyDown={onKey}>
        <span id={`${id}-value`}>{options[chosen]?.name ?? ""}</span>
        <svg aria-hidden="true" width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M2.5 4.5L6 8l3.5-3.5" /></svg>
      </button>
      {open && (
        <ul id={`${id}-list`} role="listbox" aria-labelledby={`${id}-label`}>
          {options.map((o, i) => (
            <li key={o.id} id={`${id}-${i}`} role="option" aria-selected={o.id === value} className={i === at ? "at" : undefined}
                onPointerEnter={() => setAt(i)} onPointerDown={(e) => e.preventDefault()} onClick={() => choose(i)}>
              <span aria-hidden="true" className="sq" style={o.id === value ? undefined : { visibility: "hidden" }} /><span>{o.name}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
