import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useOrganizationRequestOptions } from "@/hooks/data";
import { cn } from "@/ui/primitives";

export const ORGANIZATION_REQUESTS_PAUSED_MESSAGE = "این بخش بزودی فعال میشود";

export function RequestAccessLink({ to, className, children, ...props }: {
  to: string;
  className?: string;
  children: ReactNode;
  "data-testid"?: string;
}) {
  const { data, isSuccess } = useOrganizationRequestOptions();
  if (isSuccess && data.accepting_requests === true) {
    return <Link to={to} className={className} {...props}>{children}</Link>;
  }
  return (
    <button type="button" disabled title={ORGANIZATION_REQUESTS_PAUSED_MESSAGE}
      className={cn(className, "cursor-not-allowed opacity-50 grayscale")} {...props}>
      {children}
    </button>
  );
}
