import { useEffect } from "react";
import { BRAND } from "@/brand";
import { PublicFooter, PublicHeader } from "./chrome";
import { Hero } from "./landing/Hero";
import { CtaSection, FaqSection, HowSection, ProductSection, TrustSection } from "./landing/ProductSections";
import { InventorySection, ProblemSection } from "./landing/StorySections";
import { ScrollTrigger } from "./motion";

export default function LandingPage() {
  useEffect(() => {
    document.title = `${BRAND.name} — ${BRAND.tagline}`;
    // فونت‌ها و تصاویر ارتفاع بخش‌ها را عوض می‌کنند؛ نقاط شروع/پایان انیمیشن‌ها دوباره محاسبه شوند
    document.fonts?.ready.then(() => ScrollTrigger.refresh());
    // اگر با لینک لنگردار (مثل /#faq) آمده‌اند، بعد از رندر به آن بخش برو
    if (location.hash) requestAnimationFrame(() => document.querySelector(location.hash)?.scrollIntoView());
  }, []);

  return (
    <div className="min-h-svh bg-bg text-text" data-testid="landing">
      <PublicHeader landing />
      <main>
        <Hero />
        <ProblemSection />
        <InventorySection />
        <ProductSection />
        <HowSection />
        <TrustSection />
        <FaqSection />
        <CtaSection />
      </main>
      <PublicFooter />
    </div>
  );
}
