/** مودال، منوی کشویی و راهنمای کوچک — بر پایه Radix (دسترس‌پذیر، کیبورد، فوکوس) */
import type { ReactNode } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import * as Dropdown from "@radix-ui/react-dropdown-menu";
import * as RadixTooltip from "@radix-ui/react-tooltip";
import { X } from "lucide-react";
import { cn } from "./primitives";

const MODAL_SIZES = { sm: "max-w-md", md: "max-w-xl", lg: "max-w-3xl", xl: "max-w-5xl" };

export function Modal({ open, onClose, title, description, children, footer, size = "md", testId }: {
  open: boolean; onClose: () => void; title: ReactNode; description?: ReactNode; children: ReactNode;
  footer?: ReactNode; size?: keyof typeof MODAL_SIZES; testId?: string;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={o => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/50 backdrop-blur-[2px] data-[state=open]:animate-[rise_.2s_ease-out]" />
        <Dialog.Content data-testid={testId} dir="rtl"
          className={cn("fixed inset-x-3 top-[4vh] z-50 mx-auto flex max-h-[92vh] flex-col rounded-2xl border border-border bg-surface shadow-float",
            "data-[state=open]:animate-[rise_.25s_cubic-bezier(.2,.7,.2,1)]", MODAL_SIZES[size])}>
          <div className="flex items-start justify-between gap-4 border-b border-border px-6 py-4">
            <div>
              <Dialog.Title className="text-lg font-bold">{title}</Dialog.Title>
              {description ? <Dialog.Description className="mt-0.5 text-sm text-muted">{description}</Dialog.Description>
                : <Dialog.Description className="sr-only">{typeof title === "string" ? title : "پنجره"}</Dialog.Description>}
            </div>
            <Dialog.Close className="grid size-8 place-items-center rounded-lg text-muted transition hover:bg-surface-2 hover:text-text" aria-label="بستن">
              <X className="size-4" />
            </Dialog.Close>
          </div>
          <div className="flex-1 overflow-y-auto px-6 py-5">{children}</div>
          {footer && <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border px-6 py-4">{footer}</div>}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function Menu({ trigger, children, align = "end" }: { trigger: ReactNode; children: ReactNode; align?: "start" | "end" }) {
  return (
    <Dropdown.Root dir="rtl">
      <Dropdown.Trigger asChild>{trigger}</Dropdown.Trigger>
      <Dropdown.Portal>
        <Dropdown.Content align={align} sideOffset={8}
          className="z-50 min-w-48 rounded-xl border border-border bg-surface p-1.5 shadow-float data-[state=open]:animate-[rise_.15s_ease-out]">
          {children}
        </Dropdown.Content>
      </Dropdown.Portal>
    </Dropdown.Root>
  );
}

export function MenuItem({ children, onSelect, icon, danger }: { children: ReactNode; onSelect?: () => void; icon?: ReactNode; danger?: boolean }) {
  return (
    <Dropdown.Item onSelect={onSelect}
      className={cn("flex cursor-pointer select-none items-center gap-2 rounded-lg px-3 py-2 text-sm outline-none transition",
        danger ? "text-danger data-[highlighted]:bg-danger-soft" : "text-text-2 data-[highlighted]:bg-surface-2 data-[highlighted]:text-text")}>
      {icon}{children}
    </Dropdown.Item>
  );
}

export function MenuLabel({ children }: { children: ReactNode }) {
  return <Dropdown.Label className="px-3 py-1.5 text-xs text-muted">{children}</Dropdown.Label>;
}
export function MenuSeparator() {
  return <Dropdown.Separator className="my-1 h-px bg-border" />;
}

export function Tooltip({ content, children }: { content: ReactNode; children: ReactNode }) {
  return (
    <RadixTooltip.Provider delayDuration={250}>
      <RadixTooltip.Root>
        <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
        <RadixTooltip.Portal>
          <RadixTooltip.Content sideOffset={6} className="z-50 rounded-lg bg-text px-2.5 py-1.5 text-xs text-bg shadow-float">
            {content}
          </RadixTooltip.Content>
        </RadixTooltip.Portal>
      </RadixTooltip.Root>
    </RadixTooltip.Provider>
  );
}
