/** کارت یک مدرک: پیش‌نمایش و مشاهده، بررسی حجم/مدت پیش از آپلود، آپلود با نوار پیشرفت، و ضبط ویدیو با دوربین */
import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Camera, Check, Eye, FileUp, Loader2, Play, RotateCcw, Square, Video } from "lucide-react";
import { authFetch, errorMessage, type Schemas } from "@/api/client";
import {
  DOCUMENTS, MAX_IMAGE_MB, MAX_VIDEO_MB, MAX_VIDEO_SECONDS, compressImage, uploadWithProgress, videoDuration, type DocumentKind,
} from "@/lib/driver";
import { Modal } from "@/ui/overlays";
import { Button, cn } from "@/ui/primitives";

type Doc = Schemas["DriverDocumentInfo"];
const MB = 1024 * 1024;
const fa = (n: number) => n.toLocaleString("fa-IR", { maximumFractionDigits: 1 });

/** فایل مدرک به‌صورت blob URL (با توکن؛ فایل‌ها آدرس عمومی ندارند) */
export function useDocumentUrl(url: string, doc?: Doc | null) {
  return useQuery({
    queryKey: ["driver-doc", url, doc?.uploaded_at],
    queryFn: async () => {
      const res = await authFetch(url);
      if (!res.ok) return null;
      return URL.createObjectURL(await res.blob());
    },
    enabled: !!doc,
    staleTime: Infinity,
  }).data ?? null;
}

/** حجم و مدت را قبل از آپلود بررسی می‌کند تا راننده منتظر آپلود بی‌نتیجه نماند */
async function validate(file: Blob, isVideo: boolean): Promise<string | null> {
  if (isVideo) {
    if (file.size > MAX_VIDEO_MB * MB) return `حجم ویدیو ${fa(file.size / MB)} مگابایت است؛ حداکثر ${fa(MAX_VIDEO_MB)} مگابایت مجاز است.`;
    const seconds = await videoDuration(file);
    if (seconds !== null && seconds > MAX_VIDEO_SECONDS + 0.5)
      return `ویدیو ${fa(Math.round(seconds))} ثانیه است؛ حداکثر ${fa(MAX_VIDEO_SECONDS)} ثانیه مجاز است. یک ویدیوی کوتاه بگیرید یا «ضبط با دوربین» را بزنید.`;
  } else if (file.size > MAX_IMAGE_MB * MB) {
    return `حجم عکس ${fa(file.size / MB)} مگابایت است؛ حداکثر ${fa(MAX_IMAGE_MB)} مگابایت مجاز است.`;
  }
  return null;
}

export function DocumentSlot({ kind, doc, fileUrl, uploadUrl, required, disabled, onUploaded, onError }: {
  kind: DocumentKind; doc?: Doc | null; fileUrl: string; uploadUrl: string; required: boolean; disabled?: boolean;
  onUploaded: (result: unknown) => void; onError: (message: string) => void;
}) {
  const meta = DOCUMENTS[kind];
  const isVideo = kind === "video";
  const input = useRef<HTMLInputElement>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [recording, setRecording] = useState(false);
  const [viewing, setViewing] = useState(false);
  const preview = useDocumentUrl(fileUrl, doc);
  const canRecord = isVideo && typeof MediaRecorder !== "undefined" && !!navigator.mediaDevices?.getUserMedia;

  async function upload(file: Blob, filename: string) {
    setProgress(0);
    try {
      const body = isVideo ? file : await compressImage(file as File);
      const problem = await validate(body, isVideo);
      if (problem) { onError(problem); return; }
      const result = await uploadWithProgress<unknown>(uploadUrl, body, filename, setProgress);
      onUploaded(result);
    } catch (e) {
      onError(errorMessage(e));
    } finally {
      setProgress(null);
      if (input.current) input.current.value = "";
    }
  }

  return (
    <div className={cn("flex gap-3 rounded-2xl border p-3 transition", doc ? "border-success/40 bg-success-soft/40" : "border-border bg-surface")}
      data-testid={`doc-${kind}`} data-uploaded={!!doc}>
      <button type="button" disabled={!doc || !preview} onClick={() => setViewing(true)} aria-label={`مشاهده ${meta.label}`}
        className="group relative grid size-20 shrink-0 place-items-center overflow-hidden rounded-xl bg-surface-2 disabled:cursor-default">
        {doc && preview ? (
          <>
            {isVideo
              ? <video src={`${preview}#t=0.1`} className="size-full object-cover" muted playsInline preload="metadata" />
              : <img src={preview} alt={meta.label} className="size-full object-cover" />}
            <span className="absolute inset-0 grid place-items-center bg-black/30 text-white opacity-90 transition group-hover:bg-black/45">
              {isVideo ? <Play className="size-6 fill-white" /> : <Eye className="size-5 opacity-0 group-hover:opacity-100" />}
            </span>
          </>
        ) : isVideo ? <Video className="size-7 text-muted" /> : <Camera className="size-7 text-muted" />}
      </button>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="font-semibold">{meta.label}</span>
          {doc ? <span className="flex items-center gap-1 text-xs font-medium text-success"><Check className="size-3.5" />بارگذاری شد</span>
            : required && <span className="text-xs text-danger">الزامی</span>}
        </div>
        <p className="mt-0.5 text-xs leading-5 text-muted">{meta.hint}</p>
        {progress !== null ? (
          <div className="mt-2 flex items-center gap-2" data-testid={`doc-progress-${kind}`}>
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-2">
              <div className="h-full rounded-full bg-brand transition-[width]" style={{ width: `${Math.round(progress * 100)}%` }} />
            </div>
            <Loader2 className="size-4 animate-spin text-brand" />
          </div>
        ) : (
          <div className="mt-2 flex flex-wrap gap-2">
            {doc && preview && <Button type="button" size="sm" variant="secondary" icon={isVideo ? <Play className="size-4" /> : <Eye className="size-4" />}
              onClick={() => setViewing(true)} data-testid={`doc-view-${kind}`}>{isVideo ? "پخش" : "مشاهده"}</Button>}
            {!disabled && <>
              <Button type="button" size="sm" variant={doc ? "ghost" : "soft"} icon={<FileUp className="size-4" />}
                onClick={() => input.current?.click()}>{doc ? "تعویض" : isVideo ? "انتخاب ویدیو" : "انتخاب / عکس گرفتن"}</Button>
              {canRecord && <Button type="button" size="sm" variant="soft" icon={<Video className="size-4" />} onClick={() => setRecording(true)}
                data-testid="record-video">ضبط با دوربین</Button>}
            </>}
          </div>
        )}
        <input ref={input} type="file" hidden accept={isVideo ? "video/mp4,video/webm,video/quicktime" : "image/png,image/jpeg,image/webp"}
          capture={meta.capture} data-testid={`doc-input-${kind}`}
          onChange={e => { const f = e.target.files?.[0]; if (f) upload(f, f.name); }} />
      </div>

      {recording && <VideoRecorder onClose={() => setRecording(false)} onDone={blob => { setRecording(false); upload(blob, "selfie-video.webm"); }} />}
      {viewing && preview && (
        <Modal open onClose={() => setViewing(false)} title={meta.label} size="lg" testId="doc-viewer">
          {isVideo
            ? <video src={preview} controls autoPlay playsInline className="max-h-[70vh] w-full rounded-xl bg-black" data-testid="doc-viewer-video" />
            : <img src={preview} alt={meta.label} className="mx-auto max-h-[70vh] rounded-xl object-contain" />}
        </Modal>
      )}
    </div>
  );
}

type Phase = "starting" | "live" | "recording" | "review" | "error";

/**
 * ضبط ویدیوی کوتاه احراز هویت با دوربین جلو.
 * دوربین فقط در حالت «زنده/ضبط» روشن است؛ پس از ضبط خاموش می‌شود و ویدیوی ضبط‌شده
 * در یک المان جدا پخش می‌شود (المان دوربین زنده دوباره استفاده نمی‌شود).
 */
function VideoRecorder({ onClose, onDone }: { onClose: () => void; onDone: (blob: Blob) => void }) {
  const liveRef = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const [phase, setPhase] = useState<Phase>("starting");
  const [elapsed, setElapsed] = useState(0);
  const [result, setResult] = useState<{ blob: Blob; url: string } | null>(null);

  const stopCamera = useCallback(() => {
    stream.current?.getTracks().forEach(t => t.stop());
    stream.current = null;
  }, []);

  const startCamera = useCallback(async () => {
    setPhase("starting");
    try {
      const s = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user", width: { ideal: 640 } }, audio: true });
      stream.current = s;
      setPhase("live");
    } catch {
      setPhase("error");
    }
  }, []);

  // اتصال جریان دوربین به المان زنده، هر بار که آن المان ساخته می‌شود
  useEffect(() => {
    if ((phase === "live" || phase === "recording") && liveRef.current && stream.current && liveRef.current.srcObject !== stream.current) {
      liveRef.current.srcObject = stream.current;
    }
  }, [phase]);

  useEffect(() => { startCamera(); return stopCamera; }, [startCamera, stopCamera]);
  useEffect(() => () => { if (result) URL.revokeObjectURL(result.url); }, [result]);

  useEffect(() => {
    if (phase !== "recording") return;
    if (elapsed >= MAX_VIDEO_SECONDS_RECORD) { recorder.current?.stop(); return; }
    const t = setTimeout(() => setElapsed(e => e + 1), 1000);
    return () => clearTimeout(t);
  }, [phase, elapsed]);

  function start() {
    if (!stream.current) return;
    const chunks: Blob[] = [];
    const type = ["video/webm;codecs=vp9,opus", "video/webm", "video/mp4"].find(t => MediaRecorder.isTypeSupported(t));
    const rec = new MediaRecorder(stream.current, { mimeType: type, videoBitsPerSecond: 900_000 });
    rec.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
    rec.onstop = () => {
      const blob = new Blob(chunks, { type: (rec.mimeType || "video/webm").split(";")[0] });
      stopCamera();   // دوربین خاموش؛ حالا فقط ویدیوی ضبط‌شده نمایش داده می‌شود
      setResult({ blob, url: URL.createObjectURL(blob) });
      setPhase("review");
    };
    recorder.current = rec;
    rec.start(250);
    setElapsed(0);
    setPhase("recording");
  }

  function retake() {
    setResult(null);
    startCamera();
  }

  return (
    <Modal open onClose={() => { recorder.current?.state === "recording" && recorder.current.stop(); onClose(); }}
      title="ضبط ویدیوی احراز هویت" size="sm" testId="video-recorder"
      description="به دوربین نگاه کنید، سر را آرام به چپ و راست بچرخانید و نام کامل خود را بگویید."
      footer={phase === "review" ? <>
        <Button variant="secondary" icon={<RotateCcw className="size-4" />} onClick={retake} data-testid="recorder-retake">ضبط دوباره</Button>
        <Button icon={<Check className="size-4" />} onClick={() => result && onDone(result.blob)} data-testid="recorder-use">استفاده از این ویدیو</Button>
      </> : phase === "recording"
        ? <Button variant="danger" icon={<Square className="size-4" />} onClick={() => recorder.current?.stop()} data-testid="recorder-stop">توقف</Button>
        : <Button icon={<Play className="size-4" />} onClick={start} disabled={phase !== "live"} data-testid="recorder-start">
            شروع ضبط (حداکثر {fa(MAX_VIDEO_SECONDS_RECORD)} ثانیه)</Button>}>
      {phase === "error" ? (
        <p className="rounded-xl bg-danger-soft px-4 py-3 text-sm text-danger">دسترسی به دوربین ممکن نشد. اجازه دوربین را بدهید یا ویدیو را از گالری انتخاب کنید.</p>
      ) : (
        <div className="relative overflow-hidden rounded-2xl bg-black">
          {phase === "review" && result ? (
            // key جدا: React این المان را با المان دوربین زنده یکی نمی‌کند
            <video key="recorded" src={result.url} controls autoPlay playsInline className="aspect-[3/4] w-full object-cover" data-testid="recorder-playback" />
          ) : (
            <video key="live" ref={liveRef} autoPlay muted playsInline className="aspect-[3/4] w-full -scale-x-100 object-cover" data-testid="recorder-live" />
          )}
          {phase === "starting" && <div className="absolute inset-0 grid place-items-center text-white"><Loader2 className="size-7 animate-spin" /></div>}
          {phase === "recording" && (
            <span className="absolute right-3 top-3 flex items-center gap-1.5 rounded-full bg-danger px-2.5 py-1 text-xs font-bold text-white">
              <span className="size-2 animate-pulse rounded-full bg-white" />{fa(MAX_VIDEO_SECONDS_RECORD - elapsed)}
            </span>
          )}
          {phase === "review" && <span className="absolute right-3 top-3 rounded-full bg-black/60 px-2.5 py-1 text-xs text-white">پیش‌نمایش ضبط</span>}
        </div>
      )}
    </Modal>
  );
}

/** ضبط داخل برنامه کمی کوتاه‌تر از سقف مجاز است */
const MAX_VIDEO_SECONDS_RECORD = 10;
