/**
 * مرکز اقدام: بالای صفحه ورود هر نقش، فقط کارهایی که الان اقدام می‌خواهند.
 * هر کارت می‌گوید چه شده، چرا مهم است، مسئولش کیست و قدم بعدی چیست؛ عددش همان طول فهرستی است که دکمه‌اش باز می‌کند.
 */
import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, CheckCircle2, ChevronDown, Info, UserRound } from "lucide-react";
import { api, unwrap, type Schemas } from "@/api/client";
import { faNumber } from "@/lib/format";
import { Badge, Card, ErrorState, Skeleton, cn, toneColor } from "@/ui/primitives";

type ActionCard = Schemas["ActionCard"];
const FIRST = 4;
const SAMPLE_ROWS = 3;

export function ActionCenter({ compact = false }: { compact?: boolean }) {
  const [all, setAll] = useState(false);
  const { data, error, refetch, isLoading } = useQuery({
    queryKey: ["action-center"],
    queryFn: () => unwrap(api.GET("/action-center")),
    refetchInterval: 30_000,
  });

  if (isLoading) return (
    <div className="mb-6 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      {Array.from({ length: compact ? 2 : 4 }, (_, i) => <Skeleton key={i} className="h-44 rounded-2xl" />)}
    </div>
  );
  if (error) return <div className="mb-6"><ErrorState error={error} onRetry={refetch} /></div>;
  const cards = data?.cards ?? [];
  if (!cards.length) return (
    <Card className="mb-6 flex items-center gap-3 px-5 py-4" data-testid="action-center-empty">
      <CheckCircle2 className="size-5 text-success" />
      <div>
        <div className="font-semibold">کار فوری‌ای نیست</div>
        <div className="text-sm text-muted">هر چه نیاز به اقدام داشته باشد همین‌جا نمایش داده می‌شود.</div>
      </div>
    </Card>
  );
  const shown = all ? cards : cards.slice(0, FIRST);

  return (
    <section className="mb-6" data-testid="action-center" aria-label="نیازمند اقدام">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-base font-bold">نیازمند اقدام</h2>
        {cards.length > FIRST && (
          <button type="button" onClick={() => setAll(v => !v)} data-testid="action-center-all"
            className="tap-target inline-flex items-center gap-1 text-sm font-medium text-brand hover:underline">
            {all ? "کمتر" : `مشاهده همه (${faNumber(cards.length)})`}
            <ChevronDown className={cn("size-4 transition-transform duration-200", all && "rotate-180")} />
          </button>
        )}
      </div>
      <div className={cn("grid gap-4 md:grid-cols-2", !compact && "xl:grid-cols-4")}>
        {shown.map(card => <ActionCardView key={card.key} card={card} compact={compact} />)}
      </div>
    </section>
  );
}

/** compact: کارت‌هایی که به همین صفحه اشاره می‌کنند (صفحه راننده) دکمه رفتن ندارند؛ نمونه‌ها مستقیم به ردیف می‌روند */
function ActionCardView({ card, compact }: { card: ActionCard; compact: boolean }) {
  const Icon = card.tone === "info" ? Info : AlertTriangle;
  const rest = card.count - Math.min(card.items.length, SAMPLE_ROWS);
  return (
    <Card className="relative flex flex-col overflow-hidden" data-testid={`action-card-${card.key}`}>
      <span className="absolute inset-y-0 start-0 w-1" style={{ background: toneColor(card.tone) }} aria-hidden />
      <div className="flex items-start gap-3 px-5 pb-3 pt-4">
        <span className="grid size-9 shrink-0 place-items-center rounded-xl" style={{ color: toneColor(card.tone) }}>
          <Icon className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <h3 className="text-sm font-semibold leading-6">{card.title}</h3>
            <Badge tone={card.tone} className="shrink-0 text-sm" ><span data-testid="action-count">{faNumber(card.count)}</span></Badge>
          </div>
          <p className="mt-1 text-xs leading-5 text-muted">{card.why}</p>
        </div>
      </div>
      {card.items.length > 0 && (
        <ul className="mx-5 divide-y divide-border rounded-xl border border-border">
          {card.items.slice(0, SAMPLE_ROWS).map(item => (
            <li key={`${item.id}-${item.link}`}>
              <Link to={item.link} className="flex items-center justify-between gap-2 px-3 py-2 text-sm transition-colors hover:bg-surface-2">
                <span className="truncate font-medium">{item.label}</span>
                <span className="truncate text-xs text-muted">{item.sub}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-auto space-y-3 px-5 pb-4 pt-3">
        <p className="flex items-center gap-1.5 text-xs text-text-2">
          <UserRound className="size-3.5 shrink-0 text-muted" />
          <span className="text-muted">{card.owner}:</span> {card.next_action}
        </p>
        {!compact && <Link to={card.link} data-testid={`action-go-${card.key}`}
          className="inline-flex items-center gap-1 text-sm font-semibold text-brand hover:underline">
          {card.action_label}{rest > 0 ? ` (${faNumber(rest)} مورد دیگر)` : ""}
          <ArrowLeft className="size-4" />
        </Link>}
      </div>
    </Card>
  );
}
