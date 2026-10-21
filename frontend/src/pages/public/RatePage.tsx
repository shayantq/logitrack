/**
 * صفحه عمومی نظرسنجی مشتری درباره راننده (/rate/:token) — یک‌بار، بدون نیاز به ورود.
 * - برچسب‌ها متناسب با ستاره‌اند: ۴ و ۵ ← فقط مثبت، ۱ و ۲ ← فقط منفی، ۳ ← هر دو
 * - برچسب‌ها جدا از متن نظر ارسال می‌شوند؛ کادر توضیح خالی می‌ماند تا مشتری هرچه بخواهد بنویسد
 * - پس از ثبت، باز کردن دوباره لینک «منقضی شده» نشان می‌دهد
 */
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle2, Clock4, Package, ThumbsDown, ThumbsUp } from "lucide-react";
import { ApiError, api, errorMessage, unwrap } from "@/api/client";
import { BRAND } from "@/brand";
import { StarInput, Stars } from "@/components/performance/PerformanceUI";
import { faDate } from "@/lib/format";
import { Logo, ThemeToggle } from "@/ui/brand";
import { Button, Spinner, Textarea, cn } from "@/ui/primitives";

const LABELS = ["", "خیلی بد", "بد", "معمولی", "خوب", "عالی"];

export default function RatePage() {
  const { code = "" } = useParams();
  const [score, setScore] = useState(0);
  const [tags, setTags] = useState<string[]>([]);
  const [comment, setComment] = useState("");
  useEffect(() => { document.title = `نظرسنجی تحویل — ${BRAND.nameFa}`; }, []);
  const info = useQuery({
    queryKey: ["public-rating", code],
    queryFn: () => unwrap(api.GET("/public/ratings/{token}", { params: { path: { token: code } } })),
    retry: false, refetchOnWindowFocus: false,
  });
  const submit = useMutation({
    mutationFn: () => unwrap(api.POST("/public/ratings/{token}", { params: { path: { token: code } }, body: { score, tags, comment: comment.trim() || null } })),
  });

  const good = info.data?.good_tags ?? [];
  const bad = info.data?.bad_tags ?? [];
  const shown = score >= 4 ? good : score >= 1 && score <= 2 ? bad : score === 3 ? [...good, ...bad] : [];
  // با تغییر ستاره، برچسب‌هایی که دیگر مناسب نیستند حذف می‌شوند
  useEffect(() => { setTags(t => t.filter(x => shown.includes(x))); }, [score]); // eslint-disable-line react-hooks/exhaustive-deps
  const toggle = (tag: string) => setTags(t => (t.includes(tag) ? t.filter(x => x !== tag) : [...t, tag]));
  const expired = info.error instanceof ApiError && info.error.status === 410;

  return (
    <div className="flex min-h-svh flex-col bg-bg text-text">
      <header className="flex items-center justify-between px-4 py-4 sm:px-8"><Link to="/"><Logo /></Link><ThemeToggle /></header>
      <main className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center px-4 pb-16">
        {submit.isSuccess ? (
          <div className="card p-8 text-center" data-testid="rate-thanks">
            <CheckCircle2 className="mx-auto size-14 text-success" />
            <h1 className="mt-4 text-2xl font-black">از نظر شما سپاسگزاریم</h1>
            <div className="mt-3"><Stars value={submit.data.score} size="lg" /></div>
            <p className="mt-3 text-sm text-muted">نظر شما به {submit.data.organization_name} برای بهتر شدن خدمات کمک می‌کند.</p>
          </div>
        ) : info.isLoading ? <div className="grid place-items-center"><Spinner className="size-7" /></div> : info.error ? (
          <div className="card p-8 text-center" data-testid={expired ? "rate-expired" : "rate-invalid"}>
            <Clock4 className="mx-auto size-12 text-muted" />
            <h1 className="mt-4 text-xl font-black">{expired ? "این لینک منقضی شده است" : "لینک نظرسنجی معتبر نیست"}</h1>
            <p className="mt-2 leading-7 text-muted">{errorMessage(info.error)}</p>
          </div>
        ) : (
          <div className="card overflow-hidden" data-testid="rate-form">
            <div className="flex items-center gap-3 border-b border-border bg-brand-soft/50 p-5">
              <span className="grid size-11 place-items-center rounded-xl bg-brand text-brand-ink"><Package className="size-5" /></span>
              <div>
                <div className="text-sm text-muted">{info.data!.organization_name}</div>
                <div className="font-bold">سفارش <span className="font-mono ltr">{info.data!.tracking_code}</span> تحویل داده شد{info.data!.delivered_at && ` — ${faDate(info.data!.delivered_at)}`}</div>
              </div>
            </div>
            <div className="space-y-5 p-6 text-center">
              <h1 className="text-xl font-black">از {info.data!.driver_name ? `آقا/خانم ${info.data!.driver_name}` : "راننده"} راضی بودید؟</h1>
              <div className="flex flex-col items-center gap-2">
                <StarInput value={score} onChange={setScore} size="lg" testId="rate-stars" />
                <span className={cn("h-5 text-sm font-semibold", score >= 4 ? "text-success" : score === 3 ? "text-warning" : "text-danger")}>{LABELS[score]}</span>
              </div>
              {shown.length > 0 && (
                <div className="space-y-2" data-testid="rate-tags">
                  <div className="text-xs text-muted">{score >= 4 ? "چه چیزی خوب بود؟" : score <= 2 ? "چه مشکلی پیش آمد؟" : "چه چیزی خوب بود و چه چیزی نه؟"}</div>
                  <div className="flex flex-wrap justify-center gap-2">
                    {shown.map(tag => {
                      const positive = good.includes(tag);
                      const on = tags.includes(tag);
                      return (
                        <button key={tag} type="button" onClick={() => toggle(tag)} aria-pressed={on} data-tag={positive ? "good" : "bad"}
                          className={cn("flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs transition",
                            on ? (positive ? "border-success bg-success-soft text-success" : "border-danger bg-danger-soft text-danger") : "border-border hover:border-border-strong")}>
                          {positive ? <ThumbsUp className="size-3" /> : <ThumbsDown className="size-3" />}{tag}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
              <Textarea rows={3} maxLength={500} value={comment} onChange={e => setComment(e.target.value)} placeholder="توضیح بیشتر (اختیاری)" data-testid="rate-comment" />
              {submit.error && <p className="rounded-xl bg-danger-soft px-4 py-2.5 text-sm text-danger">{errorMessage(submit.error)}</p>}
              <Button size="lg" className="w-full" disabled={!score} loading={submit.isPending} onClick={() => submit.mutate()} data-testid="rate-submit">ثبت نظر</Button>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
