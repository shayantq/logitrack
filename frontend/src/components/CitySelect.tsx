/**
 * انتخاب شهر از فهرست رسمی شهرهای هر استان (۱۲۷۷ شهر با مختصات) — تا مقصد و مبدأ روی نقشه دقیق باشد
 * و شهر بی‌معنی ثبت نشود. سرور هم فقط همین شهرها را می‌پذیرد.
 */
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";
import { useProvinces } from "@/hooks/data";
import { Select } from "@/ui/primitives";

export const useCities = (province?: string) =>
  useQuery({
    queryKey: ["geo-cities", province || "all"],
    queryFn: () => unwrap(api.GET("/geo/cities", { params: { query: province ? { province } : {} } })),
    staleTime: Infinity,
  });

/** شهرهای یک استان؛ با عوض شدن استان، شهرِ ناهمخوان خودکار پاک می‌شود */
export function CitySelect({ province, value, onChange, required, testId, className }: {
  province: string; value: string; onChange: (city: string) => void; required?: boolean; testId?: string; className?: string;
}) {
  const { data: cities, isLoading } = useCities(province || undefined);
  const list = province ? cities ?? [] : [];
  useEffect(() => {
    if (province && cities && value && !cities.some(c => c.name === value)) onChange("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [province, cities]);
  return (
    <Select required={required} value={list.some(c => c.name === value) ? value : ""} disabled={!province || isLoading}
      onChange={e => onChange(e.target.value)} data-testid={testId} className={className} aria-label="شهر">
      <option value="">{!province ? "اول استان را انتخاب کنید" : isLoading ? "در حال بارگذاری..." : "انتخاب شهر..."}</option>
      {list.map(c => <option key={c.name} value={c.name}>{c.name}{c.capital ? " (مرکز استان)" : ""}</option>)}
    </Select>
  );
}

/** فقط شهر ذخیره می‌شود (مثل شهر فعالیت راننده/خودرو) — استان برای پیدا کردن شهر کنار آن انتخاب می‌شود */
export function CityPicker({ value, onChange, testId }: { value: string; onChange: (city: string) => void; testId?: string }) {
  const { data: provinces = [] } = useProvinces();
  const { data: all } = useCities();
  const initial = useMemo(() => all?.find(c => c.name === value)?.province ?? "", [all, value]);
  const [province, setProvince] = useState(initial);
  useEffect(() => { if (initial) setProvince(initial); }, [initial]);
  return (
    <div className="grid grid-cols-2 gap-2">
      <Select value={province} onChange={e => { setProvince(e.target.value); onChange(""); }} aria-label="استان" data-testid={testId && `${testId}-province`}>
        <option value="">استان...</option>{provinces.map(p => <option key={p} value={p}>{p}</option>)}
      </Select>
      <CitySelect province={province} value={value} onChange={onChange} testId={testId} />
    </div>
  );
}
