import { useId,useState, type ReactNode } from 'react';
import {LayoutGroup} from 'motion/react';
import {SelectionPill} from './SelectionPill';

type Choice<T extends string> = { id: T; label: string; content?: ReactNode; title?: string };

export function SegmentedControl<T extends string>({ label, value, options, onChange, className = '', onReselect }: {
  label: string;
  value: T | null;
  options: readonly Choice<T>[];
  onChange: (value: T) => void;
  className?: string;
  onReselect?: (value: T) => void;
}) {
  const [focusedValue, setFocusedValue] = useState<T | null>(null);
  const groupId=useId();
  const selectedIndex = options.findIndex(option => option.id === value);
  const focusedIndex = options.findIndex(option => option.id === focusedValue);
  const tabStopIndex = focusedIndex >= 0 ? focusedIndex : Math.max(0, selectedIndex);

  return <LayoutGroup id={groupId}><div
    className={'segmented-control ' + className}
    role="group"
    aria-label={label}
    onBlur={event => {
      if (!event.currentTarget.contains(event.relatedTarget)) setFocusedValue(null);
    }}
    onKeyDown={event => {
      if (event.altKey || event.ctrlKey || event.metaKey || !options.length) return;
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>(':scope > button'));
      const current = buttons.findIndex(button => button.contains(event.target as Node));
      const from = current >= 0 ? current : selectedIndex;
      const isRtl = getComputedStyle(event.currentTarget).direction === 'rtl';
      const step = (event.key === 'ArrowRight' ? 1 : -1) * (isRtl ? -1 : 1);
      const index = event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1
        : from < 0 ? (step > 0 ? 0 : options.length - 1)
        : (from + step + options.length) % options.length;
      const next = options[index];
      setFocusedValue(next.id);
      buttons[index]?.focus();
      if (next.id !== value) onChange(next.id);
    }}
  >{options.map((option, index) => <button
    key={option.id}
    type="button"
    aria-label={option.label}
    title={option.title}
    aria-current={value === option.id ? true : undefined}
    data-state={value === option.id ? 'active' : 'inactive'}
    tabIndex={index === tabStopIndex ? 0 : -1}
    onFocus={() => setFocusedValue(option.id)}
    onClick={() => {
      if (value === option.id) onReselect?.(option.id);
      else onChange(option.id);
    }}
  >{value===option.id&&<SelectionPill/>}<span className="segment-content">{option.content ?? option.label}</span></button>)}</div></LayoutGroup>;
}
