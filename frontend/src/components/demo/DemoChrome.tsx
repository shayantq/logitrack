/**
 * نوار و پیام خوش‌آمد نسخه نمایشی خصوصی — فقط وقتی me.is_demo است و جدا بارگذاری می‌شود
 * (بازدیدکننده عادی هیچ‌وقت این کد را دانلود نمی‌کند).
 */
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Ban, CheckCircle2, Info, RotateCcw, Sparkles } from "lucide-react";
import { useToast } from "@/components/Toast";
import { Modal } from "@/ui/overlays";
import { Button } from "@/ui/primitives";

const RESET_MINUTES = 30;
const WELCOME_KEY = "demo-welcome";

/** ثانیه‌های مانده تا ریست بعدی (سرور سر هر :00 و :30 ریست می‌کند) */
function secondsToReset(now = new Date()): number {
  const passed = (now.getMinutes() % RESET_MINUTES) * 60 + now.getSeconds();
  return RESET_MINUTES * 60 - passed;
}

const fa = (n: number) => n.toLocaleString("fa-IR", { minimumIntegerDigits: 2, useGrouping: false });

const CAN = [
  "دیدن داشبورد، شاخص‌های عملکرد و نقشه زنده ارسال‌ها",
  "ثبت سفارش، تخصیص راننده و جلو بردن وضعیت سفارش",
  "چرخه انبار: دریافت رسید، بازرسی کیفی، جانمایی، پیکینگ، بسته‌بندی و ارسال",
  "انبارگردانی: شمارش، بررسی مغایرت و تأیید",
  "بررسی و تأیید یا رد پرونده و درخواست مرخصی رانندگان",
  "پاسخ به تیکت‌های پشتیبانی",
];
const CANNOT = [
  "خروجی اکسل، PDF و CSV، چاپ برچسب و دانلود فایل",
  "ورود اطلاعات از اکسل و مهاجرت داده",
  "تعریف یا ویرایش کالا، انبار، محل، خودرو و طرف تجاری",
  "مدیریت کاربران، مجوزها، تنظیمات و پروفایل سازمان",
  "گزارش‌های مالی، ارزش‌گذاری، دفتر گردش و گزارش فعالیت",
  "ارسال پیامک یا ایمیل (هیچ پیامی واقعاً فرستاده نمی‌شود)",
];

export default function DemoChrome() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [left, setLeft] = useState(secondsToReset);
  const [open, setOpen] = useState(() => { try { return sessionStorage.getItem(WELCOME_KEY) !== "seen"; } catch { return true; } });

  useEffect(() => {
    const id = window.setInterval(() => setLeft(secondsToReset()), 1000);
    return () => window.clearInterval(id);
  }, []);

  // چند ثانیه بعد از ریست، همه داده‌های صفحه از نو خوانده می‌شوند
  useEffect(() => {
    if (left !== RESET_MINUTES * 60 - 20) return;
    void queryClient.invalidateQueries();
    toast.success("اطلاعات نسخه نمایشی به حالت اولیه برگشت.");
  }, [left, queryClient, toast]);

  const close = () => {
    try { sessionStorage.setItem(WELCOME_KEY, "seen"); } catch { /* */ }
    setOpen(false);
  };

  return (
    <>
      <div data-testid="demo-banner"
        className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 border-b border-warning/30 bg-warning-soft px-4 py-2 text-center text-xs font-medium text-text">
        <span className="inline-flex items-center gap-1.5"><Sparkles className="size-3.5 text-warning" />نسخه نمایشی — سازمان و داده‌ها فرضی‌اند</span>
        <span className="inline-flex items-center gap-1.5 text-text-2" data-testid="demo-countdown">
          <RotateCcw className="size-3.5" />بازگشت به حالت اولیه تا {fa(Math.floor(left / 60))}:{fa(left % 60)}
        </span>
        <button type="button" onClick={() => setOpen(true)} className="inline-flex items-center gap-1 font-semibold text-brand underline-offset-4 hover:underline">
          <Info className="size-3.5" />محدودیت‌ها
        </button>
      </div>
      <Modal open={open} onClose={close} size="lg" testId="demo-welcome" title="به نسخه نمایشی پسینه خوش آمدید"
        description="شما با نقش ادمین یک شرکت پخش فرضی وارد شده‌اید. همه سازمان، کالاها، سفارش‌ها و رانندگان ساختگی‌اند."
        footer={<Button onClick={close} data-testid="demo-welcome-close">شروع کنید</Button>}>
        <div className="space-y-5 text-sm leading-7">
          <section>
            <h3 className="mb-2 font-bold">چه کارهایی می‌توانید انجام دهید</h3>
            <ul className="space-y-1.5">
              {CAN.map(t => <li key={t} className="flex gap-2"><CheckCircle2 className="mt-1 size-4 shrink-0 text-success" />{t}</li>)}
            </ul>
          </section>
          <section>
            <h3 className="mb-2 font-bold">در نسخه نمایشی غیرفعال است</h3>
            <ul className="space-y-1.5">
              {CANNOT.map(t => <li key={t} className="flex gap-2"><Ban className="mt-1 size-4 shrink-0 text-danger" />{t}</li>)}
            </ul>
            <p className="mt-2 text-xs text-muted">منوهای این بخش‌ها نمایش داده نمی‌شوند و دکمه‌های مربوط پیام «غیرفعال در نسخه نمایشی» می‌دهند.</p>
          </section>
          <section className="rounded-xl bg-surface-2 p-4">
            <h3 className="mb-1 flex items-center gap-2 font-bold"><RotateCcw className="size-4 text-brand" />بازگشت خودکار به حالت اولیه</h3>
            <p className="text-text-2">
              هر ۳۰ دقیقه (سر ساعت و نیم ساعت) همه اطلاعات به حالت اولیه برمی‌گردد و تغییرات شما پاک می‌شود.
              زمان باقی‌مانده بالای صفحه نمایش داده می‌شود. هر وقت خواستید، این توضیحات را از دکمه «محدودیت‌ها» دوباره ببینید.
            </p>
          </section>
        </div>
      </Modal>
    </>
  );
}
