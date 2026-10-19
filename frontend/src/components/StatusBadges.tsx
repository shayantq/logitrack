import { Badge } from "@/ui/primitives";
import { MOVEMENT_TYPES, orderStatusLabel, orderStatusTone, VEHICLE_STATUS, VEHICLE_STATUS_TONE } from "@/lib/labels";

export function OrderStatusBadge({ status }: { status: string }) {
  return <Badge tone={orderStatusTone(status)} dot>{orderStatusLabel(status)}</Badge>;
}

export function VehicleStatusBadge({ status }: { status?: string | null }) {
  const s = status ?? "";
  return <Badge tone={VEHICLE_STATUS_TONE[s] ?? "muted"} dot>{VEHICLE_STATUS[s] ?? s ?? "—"}</Badge>;
}

export function MovementBadge({ type }: { type: string }) {
  const t = MOVEMENT_TYPES[type];
  return <Badge tone={t?.tone ?? "muted"}>{t?.label ?? type}</Badge>;
}

export function StockBadge({ stock }: { stock: number }) {
  if (stock <= 0) return <Badge tone="danger" dot>ناموجود</Badge>;
  if (stock <= 10) return <Badge tone="warning" dot>{stock.toLocaleString("fa-IR")} — رو به اتمام</Badge>;
  return <Badge tone="success" dot>{stock.toLocaleString("fa-IR")}</Badge>;
}
