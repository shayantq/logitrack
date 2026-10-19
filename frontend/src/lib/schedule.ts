/** ابزارهای هفته کاری (شنبه تا جمعه) — weekday مثل سرور/پایتون: دوشنبه=۰ ... یکشنبه=۶ */
export const WEEK: { weekday: number; name: string; short: string }[] = [
  { weekday: 5, name: "شنبه", short: "ش" }, { weekday: 6, name: "یکشنبه", short: "ی" }, { weekday: 0, name: "دوشنبه", short: "د" },
  { weekday: 1, name: "سه‌شنبه", short: "س" }, { weekday: 2, name: "چهارشنبه", short: "چ" }, { weekday: 3, name: "پنجشنبه", short: "پ" },
  { weekday: 4, name: "جمعه", short: "ج" },
];
export const WEEKDAY_NAME = Object.fromEntries(WEEK.map(w => [w.weekday, w.name])) as Record<number, string>;

export const EMPLOYMENT: Record<string, string> = { full_time: "تمام‌وقت", part_time: "پاره‌وقت" };

/** روز هفته پایتونی یک تاریخ محلی */
export const pyWeekday = (d: Date) => (d.getDay() + 6) % 7;

/** «2026-10-14» از تاریخ محلی (بدون جابه‌جایی منطقه زمانی) */
export function isoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function nextDays(count: number, from = new Date()): Date[] {
  return Array.from({ length: count }, (_, i) => new Date(from.getFullYear(), from.getMonth(), from.getDate() + i));
}

/** «08:00:00» → «08:00» */
export const hhmm = (t: string) => t.slice(0, 5);

/** شروع روز به وقت ایران به‌صورت ISO (مرخصی‌ها تمام‌روز ثبت می‌شوند) */
export const iranDayStart = (iso: string) => `${iso}T00:00:00+03:30`;

export type ShiftDraft = { weekday: number; start_time: string; end_time: string };

export const PRESETS: Record<string, { label: string; shifts: ShiftDraft[] }> = {
  full_time: {
    label: "تمام‌وقت (شنبه تا چهارشنبه ۸–۱۷، پنجشنبه ۸–۱۳)",
    shifts: [...[5, 6, 0, 1, 2].map(weekday => ({ weekday, start_time: "08:00", end_time: "17:00" })),
      { weekday: 3, start_time: "08:00", end_time: "13:00" }],
  },
  part_time: {
    label: "پاره‌وقت عصر (شنبه، دوشنبه، چهارشنبه ۱۴–۲۰)",
    shifts: [5, 0, 2].map(weekday => ({ weekday, start_time: "14:00", end_time: "20:00" })),
  },
};
