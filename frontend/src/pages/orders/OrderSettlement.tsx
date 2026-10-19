/** کرایه و تسویه منجمد سفارش + امتیاز سازمان و لینک نظرسنجی مشتری (مرحله ۸) */
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Link2, Star } from "lucide-react";
import { api, errorMessage, unwrap, type Schemas } from "@/api/client";
import { RatingTags, Rial, StarInput, Stars } from "@/components/performance/PerformanceUI";
import { useToast } from "@/components/Toast";
import { faNumber } from "@/lib/format";
import { Button, Input } from "@/ui/primitives";

export function OrderSettlement({ order }: { order: Schemas["OrderDetailResponse"] }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const finished = order.status === "delivered" || order.status === "failed";
  const { data: ratings } = useQuery({
    queryKey: ["order-rating", order.id, order.status],
    queryFn: () => unwrap(api.GET("/orders/{order_id}/rating", { params: { path: { order_id: order.id } } })),
    enabled: finished,
  });
  const [score, setScore] = useState(0);
  const [comment, setComment] = useState("");
  useEffect(() => { setScore(ratings?.organization?.score ?? 0); setComment(ratings?.organization?.comment ?? ""); }, [ratings?.organization]);
  const rate = useMutation({
    mutationFn: () => unwrap(api.PUT("/orders/{order_id}/rating", { params: { path: { order_id: order.id } }, body: { score, comment: comment || null } })),
    onSuccess: r => { queryClient.setQueryData(["order-rating", order.id, order.status], r); toast.success("امتیاز راننده ثبت شد."); },
    onError: e => toast.error(errorMessage(e)),
  });
  const link = ratings?.customer_link_token ? `${location.origin}/rate/${ratings.customer_link_token}` : null;

  const trackLink = `${location.origin}/track/${order.tracking_code}`;
  return (
    <div className="space-y-3" data-testid="order-settlement">
      <div className="flex flex-wrap items-center gap-2 rounded-xl bg-surface-2 px-4 py-2.5 text-sm">
        <span className="text-muted">لینک پیگیری برای مشتری:</span>
        <a href={trackLink} target="_blank" rel="noreferrer" className="font-mono text-xs text-brand ltr" data-testid="track-link">{trackLink}</a>
        <Button size="sm" variant="ghost" className="ms-auto" icon={<Copy className="size-4" />}
          onClick={() => navigator.clipboard?.writeText(trackLink).then(() => toast.success("لینک پیگیری کپی شد."))}>کپی</Button>
      </div>
      <div className="grid gap-3 rounded-xl border border-border p-4 text-sm sm:grid-cols-4">
        <div><div className="text-xs text-muted">کرایه حمل</div><div className="mt-0.5 font-semibold"><Rial value={order.delivery_fee} /></div></div>
        {order.status === "delivered" && order.commission_amount != null ? <>
          <div><div className="text-xs text-muted">سطح · سفر چندم روز</div><div className="mt-0.5 font-semibold">{order.commission_level} · {faNumber(order.day_trip_number)}</div></div>
          <div><div className="text-xs text-muted">پورسانت ({faNumber(order.commission_percent)}٪)</div><div className="mt-0.5 font-semibold" data-testid="settlement-commission"><Rial value={order.commission_amount} /></div></div>
          <div><div className="text-xs text-muted">سهم راننده</div><div className="mt-0.5 font-semibold text-success"><Rial value={order.driver_earning} /></div></div>
        </> : <div className="text-xs text-muted sm:col-span-3 sm:self-center">پورسانت در لحظه «تحویل داده شد» محاسبه و ثبت می‌شود.</div>}
      </div>

      {finished && ratings && (
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-xl border border-border p-4" data-testid="org-rating">
            <div className="mb-2 flex items-center gap-2 text-sm font-bold"><Star className="size-4 text-accent" />امتیاز سازمان به راننده</div>
            <StarInput value={score} onChange={setScore} testId="org-rating-stars" />
            <Input className="mt-2" placeholder="یادداشت (اختیاری)" maxLength={500} value={comment} onChange={e => setComment(e.target.value)} />
            <Button size="sm" className="mt-2" disabled={!score} loading={rate.isPending} onClick={() => rate.mutate()} data-testid="org-rating-save">
              {ratings.organization ? "به‌روزرسانی امتیاز" : "ثبت امتیاز"}</Button>
          </div>
          <div className="rounded-xl border border-border p-4" data-testid="customer-rating">
            <div className="mb-2 text-sm font-bold">نظر مشتری</div>
            {ratings.customer ? <>
              <Stars value={ratings.customer.score} size="md" />
              <div className="mt-2"><RatingTags tags={ratings.customer.tags} /></div>
              {ratings.customer.comment && <p className="mt-2 text-sm text-text-2">«{ratings.customer.comment}»</p>}
            </> : link ? <>
              <p className="text-xs leading-6 text-muted">هنوز نظری ثبت نشده. این لینک را برای مشتری بفرستید (پیامک/پیام‌رسان):</p>
              <div className="mt-2 flex gap-2">
                <Input readOnly value={link} className="ltr text-xs" data-testid="customer-link" />
                <Button size="icon" variant="secondary" aria-label="کپی لینک" onClick={() => navigator.clipboard?.writeText(link).then(() => toast.success("لینک کپی شد."))}><Copy className="size-4" /></Button>
              </div>
            </> : <p className="flex items-center gap-1.5 text-xs text-muted"><Link2 className="size-3.5" />برای سفارش ناموفق نظرسنجی مشتری ارسال نمی‌شود.</p>}
          </div>
        </div>
      )}
    </div>
  );
}
