/**
 * «نماهای من» در نوار فیلتر فهرست‌ها: فیلترهای فعلی آدرس صفحه را با یک نام ذخیره می‌کند (برای خودم یا مشترک با یک نقش)
 * و با یک کلیک دوباره اعمال می‌کند. نما همان query string صفحه است؛ پیوندهای مرکز اقدام هم همین سازوکارند.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bookmark, BookmarkPlus, Trash2, Users } from "lucide-react";
import { api, errorMessage, unwrap, type Schemas } from "@/api/client";
import { useMe } from "@/auth/AuthContext";
import { useToast } from "@/components/Toast";
import { promptDialog } from "@/ui/dialogs";
import { Menu, MenuItem, MenuLabel, MenuSeparator } from "@/ui/overlays";
import { Button } from "@/ui/primitives";

type Page = Schemas["SavedViewIn"]["page_key"];
type Filters = Record<string, string | undefined>;
type SharedRole = "org_admin" | "warehouse_manager";

const ROLE_SHARE: Record<SharedRole, string> = { org_admin: "ادمین‌های سازمان", warehouse_manager: "مدیران انبار" };

export function SavedViews({ page, filters, onApply }: { page: Page; filters: Filters; onApply: (filters: Filters) => void }) {
  const me = useMe();
  const toast = useToast();
  const queryClient = useQueryClient();
  const views = useQuery({
    queryKey: ["saved-views", page],
    queryFn: () => unwrap(api.GET("/saved-views", { params: { query: { page } } })),
    staleTime: 30_000,
  });
  const current = Object.fromEntries(Object.entries(filters).filter(([, v]) => v)) as Record<string, string>;
  const hasFilters = Object.keys(current).length > 0;
  const save = useMutation({
    mutationFn: (body: { name: string; shared_role: SharedRole | null }) =>
      unwrap(api.POST("/saved-views", { body: { page_key: page, name: body.name, filters: current, shared_role: body.shared_role } })),
    onSuccess: v => { toast.success(`نمای «${v.name}» ذخیره شد.`); queryClient.invalidateQueries({ queryKey: ["saved-views", page] }); },
    onError: e => toast.error(errorMessage(e)),
  });
  const remove = useMutation({
    mutationFn: (id: number) => unwrap(api.DELETE("/saved-views/{view_id}", { params: { path: { view_id: id } } })),
    onSuccess: () => { toast.success("نما حذف شد."); queryClient.invalidateQueries({ queryKey: ["saved-views", page] }); },
    onError: e => toast.error(errorMessage(e)),
  });

  const ask = async (shared_role: SharedRole | null) => {
    const name = await promptDialog({
      title: shared_role ? `ذخیره نما برای ${ROLE_SHARE[shared_role]}` : "ذخیره نمای فعلی",
      label: "نام نما", placeholder: "مثلاً دیرکردهای امروز", minLength: 1, maxLength: 60, confirmLabel: "ذخیره",
    });
    if (name?.trim()) save.mutate({ name: name.trim(), shared_role });
  };

  const list = views.data ?? [];
  const mine = list.filter(v => v.mine);
  return (
    <Menu trigger={
      <Button type="button" variant="ghost" icon={<Bookmark className="size-4" />} data-testid={`saved-views-${page}`}>نماهای من</Button>
    }>
      {list.length === 0 && <MenuLabel>هنوز نمایی ذخیره نشده</MenuLabel>}
      {list.map(v => (
        <MenuItem key={v.id} onSelect={() => onApply(v.filters as Filters)} icon={v.mine ? <Bookmark className="size-4" /> : <Users className="size-4" />}>
          <span data-testid="saved-view-item">{v.name}</span>
          {!v.mine && <span className="ms-auto text-xs text-muted">{v.owner_name}</span>}
        </MenuItem>
      ))}
      <MenuSeparator />
      {hasFilters ? <>
        <MenuItem onSelect={() => ask(null)} icon={<BookmarkPlus className="size-4" />}><span data-testid="saved-view-save">ذخیره نمای فعلی</span></MenuItem>
        {(["warehouse_manager", "org_admin"] as const).filter(r => me.role === "org_admin" || r === "warehouse_manager").map(r => (
          <MenuItem key={r} onSelect={() => ask(r)} icon={<Users className="size-4" />}>ذخیره برای همه {ROLE_SHARE[r]}</MenuItem>
        ))}
      </> : <MenuLabel>برای ذخیره، اول فیلتری انتخاب کنید</MenuLabel>}
      {mine.length > 0 && <>
        <MenuSeparator />
        {mine.map(v => (
          <MenuItem key={`del-${v.id}`} danger onSelect={() => remove.mutate(v.id)} icon={<Trash2 className="size-4" />}>حذف «{v.name}»</MenuItem>
        ))}
      </>}
    </Menu>
  );
}
