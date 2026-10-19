/** ورودی‌های اختصاصی فرم راننده: پلاک ایرانی و تاریخ شمسی */
import { useEffect, useState } from "react";
import { latinDigits } from "@/lib/format";
import { JALALI_MONTHS, isoToJalali, jalaliMonthLength, jalaliToIso, todayJalali } from "@/lib/jalali";
import { parsePlate } from "@/lib/driver";
import { Input, Select, cn } from "@/ui/primitives";

const FA = (s: string) => s.replace(/\d/g, d => "۰۱۲۳۴۵۶۷۸۹"[Number(d)]);
const PLATE_LETTERS = ["ا", "ب", "پ", "ت", "ث", "ج", "د", "ز", "س", "ش", "ص", "ط", "ع", "ف", "ق", "ک", "گ", "ل", "م", "ن", "و", "ه", "ی", "ژ"];
const letterLabel = (l: string) => (l === "ا" ? "الف" : l);

/** نمایش پلاک به شکل پلاک واقعی ایران */
export function PlateView({ plate, className }: { plate?: string | null; className?: string }) {
  const p = parsePlate(plate);
  if (!p) return <span className="font-mono text-sm ltr">{plate ?? "—"}</span>;
  return (
    <span dir="ltr" data-testid="plate-view"
      className={cn("inline-flex h-9 items-stretch overflow-hidden rounded-md border-2 border-text/80 bg-white font-bold text-[#111] shadow-sm", className)}>
      <span className="flex w-5 flex-col items-center justify-end bg-[#1d4ed8] pb-0.5 text-[6px] leading-none text-white">
        <span className="mb-auto mt-1 h-2 w-3 bg-[linear-gradient(#239f40_33%,#fff_33%_66%,#da0000_66%)]" />I.R.<br />IRAN
      </span>
      {p.kind === "car" ? (
        <>
          <span className="flex items-center gap-1.5 px-2 text-lg tracking-wide">
            {FA(p.a)}<span className="text-base">{letterLabel(p.letter)}</span>{FA(p.b)}
          </span>
          <span className="flex flex-col items-center justify-center border-l-2 border-text/80 px-1.5 leading-none">
            <span className="text-[8px]">ایران</span><span className="text-sm">{FA(p.region)}</span>
          </span>
        </>
      ) : (
        <span className="flex flex-col items-center justify-center px-3 leading-none">
          <span className="text-[11px]">{FA(p.region)}</span><span className="text-sm tracking-widest">{FA(p.number)}</span>
        </span>
      )}
    </span>
  );
}

/** ورودی پلاک: خودرو چهار بخش، موتورسیکلت دو بخش. خروجی: «12ب345-67» یا «123-45678» (یا "" اگر ناقص) */
export function PlateInput({ value, onChange, motorcycle }: { value?: string | null; onChange: (v: string) => void; motorcycle: boolean }) {
  const parsed = parsePlate(value);
  const [parts, setParts] = useState(() => ({
    a: parsed?.kind === "car" ? parsed.a : "", letter: parsed?.kind === "car" ? parsed.letter : "ب",
    b: parsed?.kind === "car" ? parsed.b : "", region: parsed?.region ?? "", number: parsed?.kind === "moto" ? parsed.number : "",
  }));

  useEffect(() => {
    const ok = motorcycle
      ? /^\d{3}$/.test(parts.region) && /^\d{5}$/.test(parts.number)
      : /^\d{2}$/.test(parts.a) && /^\d{3}$/.test(parts.b) && /^\d{2}$/.test(parts.region);
    onChange(!ok ? "" : motorcycle ? `${parts.region}-${parts.number}` : `${parts.a}${parts.letter}${parts.b}-${parts.region}`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [parts, motorcycle]);

  // عرض روی والد: کلاس w-full خودِ Input با عرض اختصاصی تداخل می‌کند
  const digits = (key: keyof typeof parts, len: number, placeholder: string, width: string) => (
    <div className={cn("shrink-0", width)}>
      <Input inputMode="numeric" maxLength={len} placeholder={placeholder} value={FA(parts[key])} data-testid={`plate-${key}`}
        onChange={e => setParts(p => ({ ...p, [key]: latinDigits(e.target.value).replace(/\D/g, "").slice(0, len) }))}
        className="px-1 text-center font-bold tracking-widest" />
    </div>
  );

  return (
    <div dir="ltr" className="flex w-fit items-center gap-1.5 rounded-2xl border-2 border-border-strong p-1.5" data-testid="plate-input">
      {motorcycle ? (
        <>{digits("region", 3, "۱۲۳", "w-20")}<span className="text-muted">-</span>{digits("number", 5, "۴۵۶۷۸", "w-28")}</>
      ) : (
        <>
          {digits("a", 2, "۱۲", "w-14")}
          <div className="w-20 shrink-0">
            <Select value={parts.letter} onChange={e => setParts(p => ({ ...p, letter: e.target.value }))} data-testid="plate-letter">
              {PLATE_LETTERS.map(l => <option key={l} value={l}>{letterLabel(l)}</option>)}
            </Select>
          </div>
          {digits("b", 3, "۳۴۵", "w-16")}
          <span className="px-1 text-xs font-bold text-muted">ایران</span>
          {digits("region", 2, "۶۷", "w-14")}
        </>
      )}
    </div>
  );
}

/** تاریخ شمسی با سه انتخاب (روز/ماه/سال) — مقدار و خروجی: تاریخ میلادی ISO */
export function JalaliDateInput({ value, onChange, fromYear, toYear, testId }: {
  value?: string | null; onChange: (iso: string | null) => void; fromYear: number; toYear: number; testId?: string;
}) {
  const initial = value ? isoToJalali(value) : null;
  const [y, setY] = useState(initial?.jy ?? 0);
  const [m, setM] = useState(initial?.jm ?? 0);
  const [d, setD] = useState(initial?.jd ?? 0);
  const days = y && m ? jalaliMonthLength(y, m) : 31;

  useEffect(() => {
    onChange(y && m && d && d <= days ? jalaliToIso(y, m, d) : null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [y, m, d]);

  const years = [];
  for (let i = toYear; i >= fromYear; i--) years.push(i);
  return (
    <div className="grid grid-cols-[1fr_1.4fr_1.2fr] gap-2" data-testid={testId}>
      <Select value={d} onChange={e => setD(Number(e.target.value))} aria-label="روز">
        <option value={0}>روز</option>
        {Array.from({ length: days }, (_, i) => <option key={i + 1} value={i + 1}>{FA(String(i + 1))}</option>)}
      </Select>
      <Select value={m} onChange={e => setM(Number(e.target.value))} aria-label="ماه">
        <option value={0}>ماه</option>
        {JALALI_MONTHS.map((name, i) => <option key={name} value={i + 1}>{name}</option>)}
      </Select>
      <Select value={y} onChange={e => setY(Number(e.target.value))} aria-label="سال">
        <option value={0}>سال</option>
        {years.map(year => <option key={year} value={year}>{FA(String(year))}</option>)}
      </Select>
    </div>
  );
}

export const thisJalaliYear = () => todayJalali().jy;
