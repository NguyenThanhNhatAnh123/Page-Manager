import { useEffect, useId, useRef, useState } from "react";
import {
  CalendarDays,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";

function useDismiss(
  open: boolean,
  close: () => void,
  ref: React.RefObject<HTMLDivElement | null>,
) {
  useEffect(() => {
    if (!open) return;
    const dismiss = (event: PointerEvent) => {
      if (!ref.current?.contains(event.target as Node)) close();
    };
    document.addEventListener("pointerdown", dismiss);
    return () => document.removeEventListener("pointerdown", dismiss);
  }, [open, close, ref]);
}

export function Dropdown({
  label,
  value,
  options,
  onChange,
  disabled = false,
  className = "",
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
  disabled?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(false),
    [active, setActive] = useState(0);
  const root = useRef<HTMLDivElement>(null),
    button = useRef<HTMLButtonElement>(null);
  const id = useId();
  useDismiss(open, () => setOpen(false), root);
  useEffect(() => {
    if (open)
      document
        .getElementById(`${id}-${active}`)
        ?.scrollIntoView({ block: "nearest" });
  }, [open, active, id]);
  const selected = options.findIndex((option) => option.value === value);
  function choose(index: number) {
    if (!options[index]) return;
    onChange(options[index].value);
    setOpen(false);
    button.current?.focus();
  }
  return (
    <div ref={root} className={`custom-select ${className}`}>
      <button
        ref={button}
        type="button"
        className="select-trigger"
        role="combobox"
        aria-label={label}
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        aria-haspopup="listbox"
        aria-activedescendant={open ? `${id}-${active}` : undefined}
        disabled={disabled}
        onClick={() => {
          setActive(Math.max(0, selected));
          setOpen(!open);
        }}
        onKeyDown={(event) => {
          if (event.key === "Escape" && open) {
            event.stopPropagation();
            setOpen(false);
          } else if (
            ["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)
          ) {
            event.preventDefault();
            if (!open) {
              setOpen(true);
              setActive(Math.max(0, selected));
            } else
              setActive((index) =>
                event.key === "Home"
                  ? 0
                  : event.key === "End"
                    ? options.length - 1
                    : (index +
                        (event.key === "ArrowDown" ? 1 : -1) +
                        options.length) %
                      options.length,
              );
          } else if ((event.key === "Enter" || event.key === " ") && open) {
            event.preventDefault();
            choose(active);
          } else if (event.key === "Tab") setOpen(false);
        }}
      >
        <span>{options[selected]?.label || label}</span>
        <ChevronDown size={15} className={open ? "rotated" : ""} />
      </button>
      {open && (
        <div id={id} className="select-menu" role="listbox" aria-label={label}>
          {options.map((option, index) => (
            <div
              key={option.value}
              id={`${id}-${index}`}
              role="option"
              aria-selected={option.value === value}
              className={`select-option ${index === active ? "highlighted" : ""}`}
              onPointerMove={() => setActive(index)}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => choose(index)}
            >
              <span>{option.label}</span>
              {option.value === value && <Check size={15} />}
            </div>
          ))}
          {!options.length && (
            <div className="select-empty">Chưa có lựa chọn</div>
          )}
        </div>
      )}
    </div>
  );
}

export function MonthPicker({
  value,
  today,
  onChange,
}: {
  value: string;
  today: string;
  onChange: (month: string) => void;
}) {
  const [open, setOpen] = useState(false),
    [year, setYear] = useState(Number(value.slice(0, 4)));
  const root = useRef<HTMLDivElement>(null),
    button = useRef<HTMLButtonElement>(null);
  useDismiss(open, () => setOpen(false), root);
  function choose(month: string) {
    onChange(month);
    setOpen(false);
    button.current?.focus();
  }
  return (
    <div
      ref={root}
      className="month-picker"
      onKeyDown={(event) => {
        if (event.key === "Escape" && open) {
          event.stopPropagation();
          setOpen(false);
          button.current?.focus();
        }
      }}
    >
      <button
        ref={button}
        type="button"
        className="month-trigger"
        aria-label="Chọn tháng lịch"
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => {
          setYear(Number(value.slice(0, 4)));
          setOpen(!open);
        }}
      >
        <CalendarDays size={16} />
        <span>
          Tháng {Number(value.slice(5))}, {value.slice(0, 4)}
        </span>
        <ChevronDown size={14} />
      </button>
      {open && (
        <div className="month-menu" role="dialog" aria-label="Chọn tháng">
          <div className="month-year">
            <button
              type="button"
              className="icon-button"
              aria-label="Năm trước"
              disabled={year <= 1900}
              onClick={() => setYear(year - 1)}
            >
              <ChevronLeft size={16} />
            </button>
            <strong>{year}</strong>
            <button
              type="button"
              className="icon-button"
              aria-label="Năm sau"
              disabled={year >= 2100}
              onClick={() => setYear(year + 1)}
            >
              <ChevronRight size={16} />
            </button>
          </div>
          <div className="month-options">
            {Array.from({ length: 12 }, (_, index) => {
              const month = `${year}-${String(index + 1).padStart(2, "0")}`;
              return (
                <button
                  type="button"
                  key={month}
                  aria-pressed={value === month}
                  className={value === month ? "selected" : ""}
                  onClick={() => choose(month)}
                >
                  Tháng {index + 1}
                </button>
              );
            })}
          </div>
          <button
            type="button"
            className="month-current"
            onClick={() => choose(today.slice(0, 7))}
          >
            Tháng hiện tại
            <ChevronRight size={14} />
          </button>
        </div>
      )}
    </div>
  );
}
