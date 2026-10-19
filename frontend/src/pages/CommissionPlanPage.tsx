/** قوانین کرایه، سطح‌بندی رانندگان و پورسانت پلکانی روزانه (ادمین سازمان) — با شبیه‌ساز */
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Calculator, Plus, Save, Trash2 } from "lucide-react";
import { api, errorMessage, unwrap, type Schemas } from "@/api/client";
import { useMe } from "@/auth/AuthContext";
import { LevelBadge, Rial } from "@/components/performance/PerformanceUI";
import { useToast } from "@/components/Toast";
import { faNumber, latinDigits } from "@/lib/format";
import { Button, Card, CardHeader, ErrorState, Field, Input, PageHeader, Skeleton } from "@/ui/primitives";

type Plan = Schemas["CommissionPlanIn"];
type Level = Plan["levels"][number];
const num = (v: string) => (v.trim() === "" ? 0 : Number(latinDigits(v)));

/** همان قانون سرور (app/services/commission_service.py) برای شبیه‌سازی زنده */
function simulate(plan: Plan, fee: number, deliveries: number, days: number, rating: number | null, trip: number) {
  let index = 0;
  plan.levels.forEach((lv, i) => {
    if (deliveries >= lv.min_deliveries && days >= lv.min_days && (lv.min_rating == null || (rating != null && rating >= lv.min_rating))) index = i;
  });
  let multiplier = 100;
  [...plan.tiers].sort((a, b) => a.from_trip - b.from_trip).forEach(t => { if (trip >= t.from_trip) multiplier = t.multiplier_percent; });
  const percent = (plan.levels[index].commission_percent * multiplier) / 100;
  const commission = Math.round((fee * percent) / 100);
  return { level: plan.levels[index], index, multiplier, percent, commission, earning: fee - commission };
}

export default function CommissionPlanPage() {
  const me = useMe();
  const toast = useToast();
  const queryClient = useQueryClient();
  const isAdmin = me.role === "org_admin";
  const { data, error, refetch } = useQuery({ queryKey: ["commission-plan"], queryFn: () => unwrap(api.GET("/commission-plan")) });
  const [plan, setPlan] = useState<Plan | null>(null);
  const [sim, setSim] = useState({ fee: "1000000", deliveries: "60", days: "45", rating: "4.3", trip: "6" });
  useEffect(() => { if (data) setPlan({ base_fare: data.base_fare, fare_per_kg: data.fare_per_kg, levels: data.levels, tiers: data.tiers }); }, [data]);

  const save = useMutation({
    mutationFn: () => unwrap(api.PUT("/commission-plan", { body: plan! })),
    onSuccess: p => { queryClient.setQueryData(["commission-plan"], p); toast.success("قوانین ذخیره شد؛ از سفارش‌های بعدی اعمال می‌شود."); },
    onError: e => toast.error(errorMessage(e)),
  });

  if (error) return <ErrorState error={error} onRetry={refetch} />;
  if (!plan) return <Skeleton className="h-96 rounded-2xl" />;
  const setLevel = (i: number, patch: Partial<Level>) => setPlan(p => p && ({ ...p, levels: p.levels.map((lv, j) => (j === i ? { ...lv, ...patch } : lv)) }));
  const setTier = (i: number, patch: Partial<Plan["tiers"][number]>) => setPlan(p => p && ({ ...p, tiers: p.tiers.map((t, j) => (j === i ? { ...t, ...patch } : t)) }));
  const result = simulate(plan, num(sim.fee), num(sim.deliveries), num(sim.days), sim.rating ? Number(latinDigits(sim.rating)) : null, Math.max(1, num(sim.trip)));

  return (
    <>
      <PageHeader eyebrow="تنظیمات" title="سطح‌ها و پورسانت رانندگان"
        subtitle="پورسانت = کرایه × درصد سطح راننده × ضریب پله روزانه. تغییرات فقط روی سفارش‌هایی که از این به بعد تحویل می‌شوند اثر دارد."
        actions={isAdmin && <Button icon={<Save className="size-4" />} loading={save.isPending} onClick={() => save.mutate()} data-testid="plan-save">ذخیره قوانین</Button>} />
      {data?.is_default && <p className="mb-4 rounded-xl bg-info-soft px-4 py-2.5 text-sm text-info">این قوانین پیش‌فرض سامانه است؛ با ذخیره، قوانین اختصاصی سازمان شما می‌شود.</p>}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,8fr)_minmax(0,4fr)]">
        <div className="space-y-6">
          <Card>
            <CardHeader title="کرایه پیش‌فرض" subtitle="اگر هنگام ثبت سفارش کرایه وارد نشود: پایه + (وزن × هر کیلو)، گرد به هزار ریال" />
            <div className="grid gap-4 p-5 sm:grid-cols-2">
              <Field label="کرایه پایه (ریال)"><Input inputMode="numeric" disabled={!isAdmin} value={plan.base_fare} onChange={e => setPlan({ ...plan, base_fare: num(e.target.value) })} data-testid="plan-base" /></Field>
              <Field label="به ازای هر کیلو (ریال)"><Input inputMode="numeric" disabled={!isAdmin} value={plan.fare_per_kg} onChange={e => setPlan({ ...plan, fare_per_kg: num(e.target.value) })} /></Field>
            </div>
          </Card>

          <Card>
            <CardHeader title="سطح‌ها (از پایین به بالا)" subtitle="راننده بالاترین سطحی را می‌گیرد که همه شرط‌هایش را دارد. سطح اول بدون شرط است."
              actions={isAdmin && plan.levels.length < 10 && <Button size="sm" variant="soft" icon={<Plus className="size-4" />}
                onClick={() => { const last = plan.levels[plan.levels.length - 1]; setPlan({ ...plan, levels: [...plan.levels, { ...last, code: `L${plan.levels.length + 1}`, name: "سطح جدید", min_deliveries: last.min_deliveries + 100, min_days: last.min_days + 30 }] }); }}>سطح جدید</Button>} />
            <div className="space-y-2 p-5" data-testid="plan-levels">
              {plan.levels.map((lv, i) => (
                <div key={i} className="grid items-end gap-2 rounded-xl border border-border p-3 sm:grid-cols-[auto_70px_1fr_1fr_1fr_1fr_1fr_auto]">
                  <LevelBadge code={lv.code} index={i} size="sm" />
                  <Field label="کد"><Input disabled={!isAdmin} value={lv.code} maxLength={8} onChange={e => setLevel(i, { code: e.target.value })} /></Field>
                  <Field label="نام"><Input disabled={!isAdmin} value={lv.name} onChange={e => setLevel(i, { name: e.target.value })} /></Field>
                  <Field label="حداقل تحویل"><Input disabled={!isAdmin || i === 0} inputMode="numeric" value={lv.min_deliveries} onChange={e => setLevel(i, { min_deliveries: num(e.target.value) })} /></Field>
                  <Field label="حداقل روز"><Input disabled={!isAdmin || i === 0} inputMode="numeric" value={lv.min_days} onChange={e => setLevel(i, { min_days: num(e.target.value) })} /></Field>
                  <Field label="حداقل امتیاز"><Input disabled={!isAdmin || i === 0} inputMode="decimal" placeholder="—" value={lv.min_rating ?? ""}
                    onChange={e => setLevel(i, { min_rating: e.target.value ? Number(latinDigits(e.target.value)) : null })} /></Field>
                  <Field label="پورسانت ٪"><Input disabled={!isAdmin} inputMode="decimal" value={lv.commission_percent} onChange={e => setLevel(i, { commission_percent: num(e.target.value) })} data-testid={`level-percent-${i}`} /></Field>
                  {isAdmin && i > 0 ? <Button variant="ghost" size="icon" aria-label="حذف سطح" onClick={() => setPlan({ ...plan, levels: plan.levels.filter((_, j) => j !== i) })}><Trash2 className="size-4" /></Button> : <span />}
                </div>
              ))}
            </div>
          </Card>

          <Card>
            <CardHeader title="پله‌های روزانه (مثل اسنپ)" subtitle="از Nامین تحویل در یک روز، درصد سطح در این ضریب ضرب می‌شود — ۰ یعنی بدون پورسانت."
              actions={isAdmin && plan.tiers.length < 10 && <Button size="sm" variant="soft" icon={<Plus className="size-4" />}
                onClick={() => setPlan({ ...plan, tiers: [...plan.tiers, { from_trip: (plan.tiers[plan.tiers.length - 1]?.from_trip ?? 0) + 5, multiplier_percent: 0 }] })}>پله جدید</Button>} />
            <div className="space-y-2 p-5">
              {plan.tiers.map((t, i) => (
                <div key={i} className="flex flex-wrap items-end gap-3 rounded-xl border border-border p-3">
                  <Field label="از سفر چندم روز"><Input className="w-28" disabled={!isAdmin || i === 0} inputMode="numeric" value={t.from_trip} onChange={e => setTier(i, { from_trip: num(e.target.value) })} /></Field>
                  <Field label="ضریب ٪"><Input className="w-28" disabled={!isAdmin} inputMode="numeric" value={t.multiplier_percent} onChange={e => setTier(i, { multiplier_percent: num(e.target.value) })} /></Field>
                  <span className="pb-2.5 text-sm text-muted">{t.multiplier_percent === 100 ? "پورسانت کامل" : t.multiplier_percent === 0 ? "بدون پورسانت" : `${faNumber(t.multiplier_percent)}٪ پورسانت سطح`}</span>
                  {isAdmin && i > 0 && <Button variant="ghost" size="icon" className="ms-auto" aria-label="حذف پله" onClick={() => setPlan({ ...plan, tiers: plan.tiers.filter((_, j) => j !== i) })}><Trash2 className="size-4" /></Button>}
                </div>
              ))}
            </div>
          </Card>
        </div>

        <Card className="h-fit xl:sticky xl:top-20" data-testid="plan-simulator">
          <CardHeader title={<span className="flex items-center gap-2"><Calculator className="size-4 text-brand" />شبیه‌ساز</span>} subtitle="با قوانین بالا (حتی پیش از ذخیره)" />
          <div className="grid grid-cols-2 gap-3 p-5">
            <Field label="کرایه (ریال)" className="col-span-2"><Input inputMode="numeric" value={sim.fee} onChange={e => setSim({ ...sim, fee: e.target.value })} data-testid="sim-fee" /></Field>
            <Field label="تحویل‌های قبلی"><Input inputMode="numeric" value={sim.deliveries} onChange={e => setSim({ ...sim, deliveries: e.target.value })} data-testid="sim-deliveries" /></Field>
            <Field label="روز همکاری"><Input inputMode="numeric" value={sim.days} onChange={e => setSim({ ...sim, days: e.target.value })} /></Field>
            <Field label="امتیاز"><Input inputMode="decimal" value={sim.rating} onChange={e => setSim({ ...sim, rating: e.target.value })} /></Field>
            <Field label="سفر چندم امروز"><Input inputMode="numeric" value={sim.trip} onChange={e => setSim({ ...sim, trip: e.target.value })} data-testid="sim-trip" /></Field>
          </div>
          <div className="space-y-2 border-t border-border p-5 text-sm" data-testid="sim-result">
            <div className="flex items-center justify-between"><span className="text-muted">سطح</span><LevelBadge code={result.level.code} name={result.level.name} index={result.index} size="sm" /></div>
            <div className="flex justify-between"><span className="text-muted">درصد سطح × ضریب پله</span><span className="tnum">{faNumber(result.level.commission_percent)}٪ × {faNumber(result.multiplier)}٪ = <b>{faNumber(result.percent)}٪</b></span></div>
            <div className="flex justify-between"><span className="text-muted">پورسانت سازمان</span><b data-testid="sim-commission"><Rial value={result.commission} /></b></div>
            <div className="flex justify-between"><span className="text-muted">سهم راننده</span><b className="text-success"><Rial value={result.earning} /></b></div>
          </div>
        </Card>
      </div>
    </>
  );
}
