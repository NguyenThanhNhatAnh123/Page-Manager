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

export function isoDay(day: Date) {
  return `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`;
}
export function addDays(value: string, amount: number) {
  const day = new Date(value + "T12:00:00");
  day.setDate(day.getDate() + amount);
  return isoDay(day);
}
function addMonths(value: string, amount: number) {
  const [y, m, d] = value.split("-").map(Number);
  const last = new Date(y, m - 1 + amount + 1, 0, 12).getDate();
  return isoDay(new Date(y, m - 1 + amount, Math.min(d, last), 12));
}
const weekdayNames = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"];
export function formatDay(value: string) {
  return new Intl.DateTimeFormat("vi-VN", {
    weekday: "long",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(new Date(value + "T12:00:00"));
}

export function DatePicker({
  value,
  today,
  onChange,
  label = "Chọn ngày lịch",
}: {
  value: string;
  today: string;
  onChange: (day: string) => void;
  label?: string;
}) {
  const [open, setOpen] = useState(false),
    [focus, setFocus] = useState(value);
  const root = useRef<HTMLDivElement>(null),
    button = useRef<HTMLButtonElement>(null),
    grid = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useDismiss(open, () => setOpen(false), root);
  useEffect(() => {
    if (open)
      grid.current
        ?.querySelector<HTMLButtonElement>(`[data-day="${focus}"]`)
        ?.focus();
  }, [open, focus]);
  function choose(day: string) {
    onChange(day);
    setOpen(false);
    button.current?.focus();
  }
  const month = focus.slice(0, 7);
  const first = new Date(month + "-01T12:00:00");
  const start = new Date(first);
  start.setDate(1 - ((first.getDay() + 6) % 7));
  const days = Array.from({ length: 42 }, (_, index) => {
    const day = new Date(start);
    day.setDate(day.getDate() + index);
    return isoDay(day);
  });
  const valid = (day: string) => day >= "1900-01-01" && day <= "2100-12-31";
  function move(next: string) {
    if (valid(next)) setFocus(next);
  }
  return (
    <div
      ref={root}
      className="month-picker date-picker"
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
        aria-label={`${label}: ${formatDay(value)}`}
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => {
          setFocus(value);
          setOpen(!open);
        }}
      >
        <CalendarDays size={16} />
        <span>
          {value.slice(8, 10)}/{value.slice(5, 7)}/{value.slice(0, 4)}
        </span>
        <ChevronDown size={14} />
      </button>
      {open && (
        <div
          className="month-menu date-menu"
          role="dialog"
          aria-modal="false"
          aria-labelledby={titleId}
        >
          <div className="month-year">
            <button
              type="button"
              className="icon-button"
              aria-label="Tháng trước"
              onClick={() => move(addMonths(focus, -1))}
            >
              <ChevronLeft size={16} />
            </button>
            <strong id={titleId} aria-live="polite">
              Tháng {Number(month.slice(5))}, {month.slice(0, 4)}
            </strong>
            <button
              type="button"
              className="icon-button"
              aria-label="Tháng sau"
              onClick={() => move(addMonths(focus, 1))}
            >
              <ChevronRight size={16} />
            </button>
          </div>
          <div
            ref={grid}
            className="date-grid"
            role="grid"
            aria-labelledby={titleId}
            onKeyDown={(event) => {
              const steps: Record<string, () => string> = {
                ArrowLeft: () => addDays(focus, -1),
                ArrowRight: () => addDays(focus, 1),
                ArrowUp: () => addDays(focus, -7),
                ArrowDown: () => addDays(focus, 7),
                PageUp: () => addMonths(focus, -1),
                PageDown: () => addMonths(focus, 1),
                Home: () =>
                  addDays(
                    focus,
                    -((new Date(focus + "T12:00:00").getDay() + 6) % 7),
                  ),
                End: () =>
                  addDays(
                    focus,
                    6 - ((new Date(focus + "T12:00:00").getDay() + 6) % 7),
                  ),
              };
              if (steps[event.key]) {
                event.preventDefault();
                move(steps[event.key]());
              }
            }}
          >
            <div role="row" className="date-row">
              {weekdayNames.map((name) => (
                <span key={name} role="columnheader" className="date-weekday">
                  {name}
                </span>
              ))}
            </div>
            {Array.from({ length: 6 }, (_, row) => (
              <div role="row" className="date-row" key={row}>
                {days.slice(row * 7, row * 7 + 7).map((day) => (
                  <span role="gridcell" key={day}>
                    <button
                      type="button"
                      data-day={day}
                      tabIndex={day === focus ? 0 : -1}
                      aria-label={formatDay(day)}
                      aria-pressed={day === value}
                      aria-current={day === today ? "date" : undefined}
                      className={[
                        "date-cell",
                        day === value ? "selected" : "",
                        day === today ? "today" : "",
                        day.slice(0, 7) !== month ? "outside" : "",
                      ].join(" ")}
                      onClick={() => choose(day)}
                    >
                      {Number(day.slice(8))}
                    </button>
                  </span>
                ))}
              </div>
            ))}
          </div>
          <button
            type="button"
            className="month-current"
            onClick={() => choose(today)}
          >
            Hôm nay
            <ChevronRight size={14} />
          </button>
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
