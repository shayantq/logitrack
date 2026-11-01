/** صفحه‌های راهکارها، صنایع، قابلیت‌ها، یکپارچگی، امنیت و راهنما. محتوا در content/marketing.ts است و فقط چیزی را می‌گوید که محصول واقعاً دارد. */
import { Link } from "react-router-dom";
import { Check, Minus } from "lucide-react";
import { InfoLayout } from "./InfoLayout";
import { MARKETING_PAGES, type MarketingKey } from "./content/marketing";

export default function MarketingPage({ page }: { page: MarketingKey }) {
  const content = MARKETING_PAGES[page];
  return (
    <InfoLayout title={content.title} eyebrow={content.eyebrow} heading={content.heading} lead={content.lead} testId={`marketing-${page}`}>
      {content.sections.map(section => (
        <section key={section.title} className="border-b border-border py-14">
          <div className="mx-auto max-w-7xl px-4 sm:px-6">
            <h2 className="text-2xl font-black sm:text-3xl">{section.title}</h2>
            {section.text && <p className="mt-3 max-w-3xl leading-8 text-text-2">{section.text}</p>}
            <div className="mt-8 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {section.items.map(item => (
                <article key={item.title} className="card p-5" data-testid="marketing-item">
                  <h3 className="flex items-start gap-2 font-bold">
                    {section.negative ? <Minus className="mt-1 size-4 shrink-0 text-muted" aria-hidden /> : <Check className="mt-1 size-4 shrink-0 text-success" aria-hidden />}
                    {item.title}
                  </h3>
                  <p className="mt-2 text-sm leading-7 text-text-2">{item.text}</p>
                  {item.link && <Link to={item.link.to} className="mt-3 inline-block text-sm font-medium text-brand hover:underline">{item.link.label}</Link>}
                </article>
              ))}
            </div>
          </div>
        </section>
      ))}
    </InfoLayout>
  );
}
