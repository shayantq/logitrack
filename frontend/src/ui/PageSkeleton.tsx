import { Skeleton } from "./primitives";

/** ساختار انتظار متناسب با مقصد؛ پوستهٔ پنل بیرون از این جزء می‌ماند. */
export function PageSkeleton({ pathname = "" }: { pathname?: string }) {
  const variant = /\/(reports|finance|analytics|capacity|comparison|capital-plan)(\/|$)/.test(pathname) ? "report"
    : /^\/app\/?$/.test(pathname) || /\/(driver|dashboard)\/?$/.test(pathname) ? "dashboard"
    : /\/(organization|profile|change-password|mfa|onboarding)(\/|$)/.test(pathname) ? "form" : "list";
  return (
    <div className="min-h-[50vh] space-y-6" role="status" aria-label="در حال بارگذاری صفحه" aria-busy="true" data-testid="page-loading" data-skeleton={variant}>
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="space-y-3"><Skeleton className="h-8 w-44" /><Skeleton className="h-4 w-60 max-w-full" /></div>
        <Skeleton className="h-10 w-28" />
      </div>
      {(variant === "dashboard" || variant === "report") && <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-28" />)}
      </div>}
      {variant === "report" ? <div className="grid gap-5 lg:grid-cols-2"><Skeleton className="h-72" /><Skeleton className="h-72" /></div>
        : variant === "form" ? <div className="card grid gap-6 p-5 sm:grid-cols-2">
          {Array.from({ length: 6 }, (_, i) => <div key={i} className="space-y-2"><Skeleton className="h-4 w-24" /><Skeleton className="h-11" /></div>)}
        </div> : <div className="card space-y-4 p-5">
          <Skeleton className="h-11" />
          {Array.from({ length: variant === "list" ? 6 : 4 }, (_, i) => <Skeleton key={i} className="h-10" />)}
        </div>}
      <span className="sr-only">لطفاً منتظر بمانید.</span>
    </div>
  );
}
