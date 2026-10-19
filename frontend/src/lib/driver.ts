/** برچسب‌ها و ابزارهای احراز هویت راننده (مرحله ۶) */
import { Bike, Bus, Car, Container, Truck, type LucideIcon } from "lucide-react";
import { ApiError, errorMessage, tokenStore } from "@/api/client";
import type { Tone } from "@/ui/primitives";

export type DriverStatus = "incomplete" | "submitted" | "approved" | "rejected";
export type DocumentKind = "national_card" | "selfie" | "video" | "driving_license" | "vehicle_photo" | "vehicle_card" | "technical_inspection";

// سقف‌ها — هماهنگ با app/services/driver_service.py
export const MAX_IMAGE_MB = 5;
export const MAX_VIDEO_MB = 30;
export const MAX_VIDEO_SECONDS = 15;

/** مدت ویدیو (ثانیه) از روی خود فایل در مرورگر؛ اگر مرورگر نتواند بخواند null */
export function videoDuration(file: Blob): Promise<number | null> {
  return new Promise(resolve => {
    const url = URL.createObjectURL(file);
    const video = document.createElement("video");
    const done = (value: number | null) => { clearTimeout(timer); URL.revokeObjectURL(url); resolve(value); };
    const timer = setTimeout(() => done(null), 6000);
    video.preload = "metadata";
    video.muted = true;
    video.onloadedmetadata = () => done(Number.isFinite(video.duration) ? video.duration : null);
    video.onerror = () => done(null);
    video.src = url;
  });
}

export const DRIVER_STATUS: Record<DriverStatus, { label: string; tone: Tone }> = {
  incomplete: { label: "در حال تکمیل", tone: "muted" },
  submitted: { label: "منتظر بررسی", tone: "warning" },
  approved: { label: "تأییدشده", tone: "success" },
  rejected: { label: "ردشده", tone: "danger" },
};

export const VEHICLE_KINDS: { value: string; label: string; hint: string; icon: LucideIcon; maxKg: number }[] = [
  { value: "motorcycle", label: "موتورسیکلت", hint: "بسته‌های کوچک درون‌شهری", icon: Bike, maxKg: 150 },
  { value: "sedan", label: "سواری", hint: "تا حدود ۵۰۰ کیلوگرم", icon: Car, maxKg: 500 },
  { value: "pickup", label: "وانت / نیسان", hint: "تا حدود ۱.۵ تن", icon: Truck, maxKg: 1500 },
  { value: "van", label: "ون", hint: "تا حدود ۳.۵ تن", icon: Bus, maxKg: 3500 },
  { value: "truck", label: "کامیون", hint: "بار سنگین و بین‌شهری", icon: Container, maxKg: 30000 },
];

export const DOCUMENTS: Record<DocumentKind, { label: string; hint: string; capture?: "user" | "environment" }> = {
  national_card: { label: "کارت ملی", hint: "روی کارت، کامل و خوانا", capture: "environment" },
  selfie: { label: "عکس سلفی", hint: "صورت کامل، بدون عینک آفتابی", capture: "user" },
  video: { label: "ویدیوی احراز هویت", hint: "۵ تا ۱۰ ثانیه: سر را به چپ و راست بچرخانید و نام کامل خود را بگویید (حداکثر ۱۵ ثانیه و ۳۰ مگابایت)", capture: "user" },
  driving_license: { label: "گواهینامه", hint: "روی گواهینامه هوشمند", capture: "environment" },
  vehicle_photo: { label: "عکس وسیله", hint: "نمای کامل با پلاک خوانا", capture: "environment" },
  vehicle_card: { label: "کارت وسیله", hint: "کارت ماشین یا موتور", capture: "environment" },
  technical_inspection: { label: "برگه معاینه فنی", hint: "معاینه فنی معتبر", capture: "environment" },
};

/** نام فارسی هر مورد ناقص (کلید فیلد یا نوع مدرک) */
export const MISSING_LABELS: Record<string, string> = {
  first_name: "نام", last_name: "نام خانوادگی", national_code: "کد ملی", birth_date: "تاریخ تولد", mobile: "شماره همراه",
  province: "استان", city: "شهر", address: "نشانی", vehicle_type: "نوع وسیله", vehicle_model: "مدل وسیله",
  license_plate: "پلاک", max_weight_kg: "سقف بار", inspection_expiry: "تاریخ اعتبار معاینه فنی",
  ...Object.fromEntries(Object.entries(DOCUMENTS).map(([k, v]) => [k, v.label])),
};

/** هر مورد ناقص به کدام مرحله فرم تعلق دارد */
export const STEP_OF: Record<string, number> = {
  vehicle_type: 0,
  first_name: 1, last_name: 1, national_code: 1, birth_date: 1, mobile: 1, national_card: 1, selfie: 1, video: 1, driving_license: 1,
  vehicle_model: 2, license_plate: 2, max_weight_kg: 2, inspection_expiry: 2, vehicle_photo: 2, vehicle_card: 2, technical_inspection: 2,
  province: 3, city: 3, address: 3,
};

/** پلاک ذخیره‌شده ← اجزای نمایش: خودرو «12ب345-67»، موتور «123-45678» */
export function parsePlate(plate?: string | null) {
  if (!plate) return null;
  const car = /^(\d{2})(\D)(\d{3})-(\d{2})$/.exec(plate);
  if (car) return { kind: "car" as const, a: car[1], letter: car[2], b: car[3], region: car[4] };
  const moto = /^(\d{3})-(\d{5})$/.exec(plate);
  if (moto) return { kind: "moto" as const, region: moto[1], number: moto[2] };
  return null;
}

/**
 * عکس‌های بزرگ گوشی پیش از ارسال کوچک می‌شوند (حداکثر ۲۰۰۰ پیکسل، JPEG)؛
 * عکس‌های کوچک یا فرمت‌هایی که مرورگر نمی‌تواند باز کند، دست‌نخورده ارسال می‌شوند.
 */
export async function compressImage(file: File, maxSide = 2000): Promise<Blob> {
  if (!file.type.startsWith("image/") || file.size < 900 * 1024) return file;
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext("2d")!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    const blob = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, "image/jpeg", 0.85));
    return blob && blob.size < file.size ? blob : file;
  } catch {
    return file;
  }
}

/** آپلود با نوار پیشرفت (fetch پیشرفت آپلود را گزارش نمی‌دهد) */
export function uploadWithProgress<T>(url: string, file: Blob, filename: string, onProgress: (ratio: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    const token = tokenStore.get();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.onprogress = e => { if (e.lengthComputable) onProgress(e.loaded / e.total); };
    xhr.onload = () => {
      let body: unknown = {};
      try { body = JSON.parse(xhr.responseText || "{}"); } catch { /* پاسخ غیر JSON */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as T);
      else reject(new ApiError(errorMessage(body, "آپلود ناموفق بود."), xhr.status));
    };
    xhr.onerror = () => reject(new ApiError("ارتباط با سرور برقرار نشد؛ اینترنت را بررسی کنید.", 0));
    const form = new FormData();
    form.append("file", file, filename);
    xhr.send(form);
  });
}
