/**
 * فهرست انتخاب سفارشی — جایگزین <select> پیش‌فرض کروم با همان شکل استفاده:
 *   <Select value={v} onChange={e => set(e.target.value)}><option value="a">الف</option>…</Select>
 * فهرست بلند جست‌وجو دارد؛ کیبورد (بالا/پایین، Enter، Esc، Home/End، تایپ حرف اول) کار می‌کند.
 * یک <select> مخفی کنارش هست تا required و اعتبارسنجی فرم مثل قبل کار کند.
 */
import {
  Children, Fragment, forwardRef, isValidElement, useEffect, useImperativeHandle, useMemo, useRef, useState,
  type KeyboardEvent, type ReactNode, type SelectHTMLAttributes,
} from "react";
import { Check, ChevronDown, Search } from "lucide-react";
import { Popover } from "./popover";
import { cn } from "./primitives";

type Opt = { value: string; label: ReactNode; text: string; disabled: boolean; group?: string };

function textOf(node: ReactNode): string {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (isValidElement<{ children?: ReactNode }>(node)) return textOf(node.props.children);
  return "";
}

function collect(children: ReactNode, group?: string, out: Opt[] = []): Opt[] {
  Children.forEach(children, child => {
    if (!isValidElement<Record<string, unknown>>(child)) return;
    const props = child.props as { value?: unknown; children?: ReactNode; disabled?: boolean; label?: string };
    if (child.type === "option") {
      const text = textOf(props.children);
      out.push({ value: String(props.value ?? text), label: props.children, text, disabled: !!props.disabled, group });
    } else if (child.type === "optgroup") {
      collect(props.children, props.label, out);
    } else if (child.type === Fragment) {
      collect(props.children, group, out);
    }
  });
  return out;
}

const norm = (s: string) => s.replace(/[يى]/g, "ی").replace(/ك/g, "ک").replace(/[\s‌]/g, "").toLowerCase();
const SEARCH_FROM = 9;

export type SelectProps = Omit<SelectHTMLAttributes<HTMLSelectElement>, "onChange" | "value"> & {
  value?: string | number | readonly string[] | null;
  onChange?: (e: { target: { value: string } }) => void;
  /** جست‌وجو در فهرست (پیش‌فرض: وقتی گزینه‌ها زیاد است) */
  searchable?: boolean;
};

export const Select = forwardRef<HTMLButtonElement, SelectProps>(function Select(
  { value, onChange, children, className, disabled, required, name, searchable, id, ...rest }, ref,
) {
  const options = useMemo(() => collect(children), [children]);
  const current = String(value ?? "");
  const selected = options.find(o => o.value === current);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const trigger = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const search = useRef<HTMLInputElement>(null);
  useImperativeHandle(ref, () => trigger.current as HTMLButtonElement);

  const testId = (rest as Record<string, unknown>)["data-testid"] as string | undefined;
  const ariaLabel = rest["aria-label"];
  const withSearch = searchable ?? options.length > SEARCH_FROM;
  const visible = useMemo(() => {
    const q = norm(query);
    return q ? options.filter(o => norm(o.text).includes(q)) : options;
  }, [options, query]);

  const choose = (opt: Opt) => {
    if (opt.disabled) return;
    setOpen(false);
    setQuery("");
    trigger.current?.focus();
    if (opt.value !== current) onChange?.({ target: { value: opt.value } });
  };
  const openList = () => {
    if (disabled) return;
    setQuery("");
    setActive(Math.max(0, options.findIndex(o => o.value === current)));
    setOpen(true);
  };

  useEffect(() => {
    if (!open) return;
    requestAnimationFrame(() => {
      (withSearch ? search.current : list.current)?.focus({ preventScroll: true });
      list.current?.querySelector("[data-active=true]")?.scrollIntoView({ block: "nearest" });
    });
  }, [open, withSearch]);
  useEffect(() => { list.current?.querySelector("[data-active=true]")?.scrollIntoView({ block: "nearest" }); }, [active]);

  const move = (delta: number) => {
    if (!visible.length) return;
    let i = active;
    for (let n = 0; n < visible.length; n++) {
      i = (i + delta + visible.length) % visible.length;
      if (!visible[i].disabled) break;
    }
    setActive(i);
  };
  const onListKey = (e: KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); move(1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); move(-1); }
    else if (e.key === "Home") { e.preventDefault(); setActive(0); }
    else if (e.key === "End") { e.preventDefault(); setActive(visible.length - 1); }
    else if (e.key === "Enter") { e.preventDefault(); if (visible[active]) choose(visible[active]); }
    else if (e.key === "Tab") setOpen(false);
    else if (!withSearch && e.key.length === 1) {
      // پرش با حرف اول
      const i = visible.findIndex(o => norm(o.text).startsWith(norm(e.key)));
      if (i >= 0) setActive(i);
    }
  };

  let lastGroup: string | undefined;
  return (
    <div className="relative" data-select-root data-field-root>
      <button ref={trigger} type="button" id={id} role="combobox" aria-expanded={open} aria-haspopup="listbox"
        aria-label={ariaLabel} data-testid={testId} data-value={current} disabled={disabled} data-focus-target
        onClick={() => (open ? setOpen(false) : openList())}
        onKeyDown={e => { if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) { e.preventDefault(); openList(); } }}
        className={cn("flex h-10 w-full items-center gap-2 rounded-xl border border-border-strong bg-surface px-3.5 text-start text-sm text-text transition",
          "focus:border-brand focus:outline-none focus:ring-4 focus:ring-brand/15 disabled:cursor-not-allowed disabled:opacity-60",
          open && "border-brand ring-4 ring-brand/15", className)}>
        <span className={cn("min-w-0 flex-1 truncate", (!selected || selected.value === "") && "text-muted")}>
          {selected ? selected.label : "انتخاب کنید"}
        </span>
        <ChevronDown className={cn("size-4 shrink-0 text-muted transition-transform duration-200", open && "rotate-180 text-brand")} />
      </button>
      {/* برای اعتبارسنجی فرم (required) و ارسال با name */}
      <select tabIndex={-1} aria-hidden className="sr-only" name={name} required={required} disabled={disabled}
        value={current} onChange={() => {}} data-native-for={testId}>
        {options.map(o => <option key={o.value} value={o.value}>{o.text}</option>)}
      </select>

      <Popover anchor={trigger} open={open} onClose={() => setOpen(false)} testId={testId && `${testId}-list`}>
        {withSearch && (
          <div className="border-b border-border p-2">
            <label className="relative block">
              <Search className="pointer-events-none absolute start-2.5 top-1/2 size-4 -translate-y-1/2 text-muted" />
              <input ref={search} value={query} onChange={e => { setQuery(e.target.value); setActive(0); }} onKeyDown={onListKey}
                placeholder="جست‌وجو..." className="h-9 w-full rounded-lg bg-surface-2 ps-8 pe-2 text-sm outline-none focus:ring-2 focus:ring-brand/30" />
            </label>
          </div>
        )}
        <div ref={list} role="listbox" tabIndex={-1} onKeyDown={onListKey} data-select-list className="overflow-y-auto p-1 outline-none">
          {visible.length === 0 && <div className="px-3 py-6 text-center text-sm text-muted">موردی پیدا نشد</div>}
          {visible.map((o, i) => {
            const header = o.group && o.group !== lastGroup ? o.group : null;
            lastGroup = o.group;
            const isSelected = o.value === current;
            return (
              <Fragment key={`${o.group ?? ""}:${o.value}`}>
                {header && <div className="px-3 pb-1 pt-2.5 text-[11px] font-semibold text-muted">{header}</div>}
                <div role="option" aria-selected={isSelected} aria-disabled={o.disabled} data-value={o.value} data-active={i === active}
                  onPointerMove={() => i !== active && setActive(i)} onClick={() => choose(o)}
                  className={cn("flex cursor-pointer select-none items-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors",
                    i === active && "bg-surface-2", isSelected ? "font-semibold text-brand" : "text-text",
                    o.value === "" && !isSelected && "text-muted", o.disabled && "cursor-not-allowed opacity-40")}>
                  <span className="min-w-0 flex-1">{o.label}</span>
                  {isSelected && o.value !== "" && <Check className="size-4 shrink-0" strokeWidth={2.5} />}
                </div>
              </Fragment>
            );
          })}
        </div>
      </Popover>
    </div>
  );
});
