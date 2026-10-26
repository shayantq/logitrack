/**
 * اسکن سراسری (فصل ۲۷): هر بارکد یا QR (کالا، محل، بسته، سفارش، سند، بچ یا لینک رهگیری) را شناسایی می‌کند و
 * کاربر را مستقیم به همان مورد می‌برد. سه راه ورود: دوربین گوشی (BarcodeDetector در کروم اندروید و مرورگرهای جدید)،
 * اسکنر بی‌سیم/USB که مثل صفحه‌کلید تایپ می‌کند، یا تایپ دستی. روی مرورگرهایی که BarcodeDetector ندارند
 * (مثل Safari قدیمی) فقط ورود دستی/اسکنر نشان داده می‌شود.
 */
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Camera, ScanLine } from "lucide-react";
import { api, errorMessage, unwrap } from "@/api/client";
import { Modal, Tooltip } from "@/ui/overlays";
import { Badge, Button, Input } from "@/ui/primitives";

type Detector = { detect: (source: CanvasImageSource) => Promise<{ rawValue: string }[]> };
type DetectorCtor = new (opts?: { formats?: string[] }) => Detector;
const KIND_LABELS: Record<string, string> = {
  product: "کالا", location: "محل", package: "بسته", order: "سفارش", pick_list: "فهرست برداشت", receipt: "رسید",
  transfer: "سفارش انتقال", document: "سند انبار", stocktake: "انبارگردانی", lot: "بچ",
};

export function cameraScanSupported(): boolean {
  return typeof window !== "undefined" && "BarcodeDetector" in window && !!navigator.mediaDevices?.getUserMedia;
}

/** دوربین را باز می‌کند و اولین بارکد خوانده‌شده را برمی‌گرداند */
export function CameraScanner({ onCode }: { onCode: (code: string) => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let stream: MediaStream | null = null;
    let stopped = false;
    const Ctor = (window as unknown as { BarcodeDetector: DetectorCtor }).BarcodeDetector;
    const detector = new Ctor({ formats: ["code_128", "qr_code", "ean_13", "ean_8", "code_39", "upc_a", "data_matrix"] });
    (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
        if (!video.current || stopped) return;
        video.current.srcObject = stream;
        await video.current.play();
        const tick = async () => {
          if (stopped || !video.current) return;
          try {
            const [hit] = await detector.detect(video.current);
            if (hit?.rawValue) { onCode(hit.rawValue); return; }
          } catch { /* فریم ناقص */ }
          window.setTimeout(tick, 250);
        };
        tick();
      } catch {
        setError("دسترسی به دوربین داده نشد؛ کد را با اسکنر یا دستی وارد کنید.");
      }
    })();
    return () => { stopped = true; stream?.getTracks().forEach(t => t.stop()); };
  }, [onCode]);
  return error ? <p className="rounded-xl bg-warning-soft p-3 text-xs text-warning">{error}</p> : (
    <div className="relative overflow-hidden rounded-xl bg-black">
      <video ref={video} playsInline muted className="aspect-video w-full object-cover" />
      <div className="pointer-events-none absolute inset-x-8 top-1/2 h-0.5 -translate-y-1/2 animate-pulse bg-danger shadow-[0_0_12px_var(--danger)]" />
    </div>
  );
}

export function ScanButton() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Tooltip content="اسکن بارکد / QR">
        <Button variant="ghost" size="icon" className="size-11 lg:size-10" onClick={() => setOpen(true)} aria-label="اسکن" data-testid="scan-open">
          <ScanLine className="size-5" />
        </Button>
      </Tooltip>
      {open && <ScanDialog onClose={() => setOpen(false)} />}
    </>
  );
}

function ScanDialog({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const [code, setCode] = useState("");
  const [camera, setCamera] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [found, setFound] = useState<{ kind: string; title: string; subtitle?: string | null; path: string } | null>(null);

  const resolve = async (value: string) => {
    const clean = value.trim();
    if (!clean) return;
    setBusy(true); setError(null); setFound(null); setCamera(false); setCode(clean);
    try {
      const hit = await unwrap(api.GET("/scan/resolve", { params: { query: { code: clean } } }));
      setFound(hit);
      window.setTimeout(() => { navigate(hit.path); onClose(); }, 600);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const submit = (e: FormEvent) => { e.preventDefault(); resolve(code); };
  return (
    <Modal open onClose={onClose} title="اسکن بارکد / QR" testId="scan-modal"
      description="کالا، محل، بسته، سفارش، سند یا بچ — با دوربین، اسکنر یا تایپ دستی.">
      <form onSubmit={submit} className="space-y-3">
        <div className="flex gap-2">
          <Input autoFocus dir="ltr" value={code} onChange={e => setCode(e.target.value)} placeholder="کد را اسکن یا تایپ کنید"
            data-testid="scan-input" className="font-mono" />
          <Button type="submit" loading={busy} data-testid="scan-submit">برو</Button>
        </div>
        {cameraScanSupported() && (camera
          ? <CameraScanner onCode={resolve} />
          : <Button type="button" variant="soft" className="w-full" onClick={() => setCamera(true)} data-testid="scan-camera">
            <Camera className="size-4" /> اسکن با دوربین</Button>)}
        {found && (
          <div className="flex items-center gap-2 rounded-xl bg-success-soft p-3 text-sm" data-testid="scan-result" data-kind={found.kind}>
            <Badge tone="success">{KIND_LABELS[found.kind] ?? found.kind}</Badge>
            <span className="font-semibold">{found.title}</span>{found.subtitle && <span className="text-xs text-muted">{found.subtitle}</span>}
          </div>
        )}
        {error && <p className="rounded-xl bg-danger-soft p-3 text-sm text-danger" data-testid="scan-error">{error}</p>}
      </form>
    </Modal>
  );
}
