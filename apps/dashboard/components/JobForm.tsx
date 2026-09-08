"use client";

import { useState } from "react";
import type { JobPostingInput, SalaryInfo } from "@ars/shared-types";
import { RichTextEditor } from "@/components/RichTextEditor";
import { Field, inputClass } from "@/components/ui";
import { EMPLOYMENT_TYPE_OPTIONS, LEVEL_OPTIONS } from "@/lib/jobs";

// JD-2a: JobForm CHỈ còn màn "Tin tuyển dụng" (field posting — ứng viên thấy). Rubric + câu hỏi sàng lọc
// dời sang màn "Cấu hình sàng lọc" (ScreeningConfigForm, trên JD đã lưu); gate dời ra danh sách JD.
// rubric/screener_questions/gate_config đi XUYÊN QUA từ `initial` (không sửa ở màn này) — được làm sạch
// khi submit để không gửi item rỗng (JobPostingCreate validate criterion non-empty).

// Ô nhập / nhãn / nút lấy từ `components/ui` — KHÔNG chép chuỗi class nữa (bản cũ giữ hằng `INPUT`
// sao y `inputClass` và tự viết class cho nút submit, nên nút ở màn JD trông khác nút ở mọi màn
// khác: `font-medium` vs `font-semibold`, `disabled:opacity-50` vs `disabled:opacity-45`).
//
// Nhãn của ba trường soạn thảo (Mô tả / Yêu cầu / Quyền lợi) KHÔNG dùng `Field`: `RichTextEditor`
// không phải phần tử form gắn được `htmlFor`, nên `<label>` ở đó chỉ là chữ trang trí (tên đọc được
// thật nằm ở prop `ariaLabel` của editor). Dùng thẻ <p> để không hứa hẹn sai với trình đọc màn hình.
const GROUP_LABEL = "mb-1.5 block text-xs font-semibold text-ink/70";

function clamp01(n: number): number {
  if (!Number.isFinite(n)) return 0;
  return Math.min(1, Math.max(0, n));
}

// Ô nhập số tiền → number | null (rỗng = null; âm quy về 0).
function parseAmount(raw: string): number | null {
  const t = raw.trim();
  if (t === "") return null;
  const n = Number(t.replace(/[^\d]/g, ""));
  if (!Number.isFinite(n)) return null;
  return Math.max(0, Math.trunc(n));
}

export function JobForm({
  initial,
  onSubmit,
  submitting,
  submitLabel,
  errorMsg,
  warning,
}: {
  initial: JobPostingInput;
  onSubmit: (input: JobPostingInput) => void;
  submitting: boolean;
  submitLabel: string;
  errorMsg?: string | null;
  warning?: string | null;
}) {
  const [form, setForm] = useState<JobPostingInput>(initial);
  const [localError, setLocalError] = useState<string | null>(null);

  const set = <K extends keyof JobPostingInput>(key: K, value: JobPostingInput[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  const setSalary = (patch: Partial<SalaryInfo>) =>
    setForm((f) => ({ ...f, salary: { ...f.salary, ...patch } }));

  const salary = form.salary;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (submitting) return; // chống double-submit

    if (!salary.negotiable && salary.min != null && salary.max != null && salary.min > salary.max) {
      setLocalError("Lương tối thiểu không được lớn hơn tối đa.");
      return;
    }

    const cleaned: JobPostingInput = {
      title: form.title.trim(),
      description: form.description, // HTML (editor phát "" khi rỗng)
      requirements: form.requirements, // HTML
      level: form.level || null,
      salary: {
        min: salary.negotiable ? null : salary.min,
        max: salary.negotiable ? null : salary.max,
        currency: salary.currency,
        negotiable: salary.negotiable,
      },
      benefits: form.benefits, // HTML
      employment_type: form.employment_type || null,
      // Passthrough (cấu hình ở màn khác) — làm sạch để không gửi item rỗng.
      rubric: form.rubric
        .map((c) => ({ criterion: c.criterion.trim(), weight: clamp01(c.weight) }))
        .filter((c) => c.criterion.length > 0),
      screener_questions: form.screener_questions.map((s) => s.trim()).filter(Boolean),
      gate_config: form.gate_config,
    };
    if (!cleaned.title || !cleaned.description) {
      setLocalError("Cần nhập tiêu đề và mô tả JD.");
      return;
    }
    setLocalError(null);
    onSubmit(cleaned);
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      {/* role="alert": mọi màn khác trong repo đã có live region cho khối lỗi/cảnh báo — thiếu nó
          thì bấm Lưu xong người dùng trình đọc màn hình không nghe gì và tưởng đã lưu xong. */}
      {(localError || errorMsg) && (
        <p
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700"
        >
          {localError ?? errorMsg}
        </p>
      )}
      {warning && (
        <p
          role="alert"
          className="rounded-lg border border-orange-200 bg-orange-50 px-4 py-2 text-sm text-orange-800"
        >
          {warning}
        </p>
      )}

      {/* Tiêu đề */}
      <Field label="Tiêu đề" required htmlFor="jd-title">
        <input
          id="jd-title"
          type="text"
          value={form.title}
          onChange={(e) => set("title", e.target.value)}
          placeholder="vd: Backend Intern (Node.js)"
          className={inputClass}
        />
      </Field>

      {/* Cấp bậc + loại việc */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Cấp bậc" htmlFor="jd-level">
          <select
            id="jd-level"
            value={form.level ?? ""}
            onChange={(e) => set("level", e.target.value || null)}
            className={inputClass}
          >
            <option value="">— Chọn cấp bậc —</option>
            {LEVEL_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Loại công việc" htmlFor="jd-emptype">
          <select
            id="jd-emptype"
            value={form.employment_type ?? ""}
            onChange={(e) => set("employment_type", e.target.value || null)}
            className={inputClass}
          >
            <option value="">— Chọn loại việc —</option>
            {EMPLOYMENT_TYPE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </Field>
      </div>

      {/* Lương */}
      <fieldset className="space-y-3 rounded-lg border border-divider p-4">
        <legend className="px-1 text-sm font-medium text-ink/80">Lương</legend>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={salary.negotiable}
            onChange={(e) => setSalary({ negotiable: e.target.checked })}
            className="h-4 w-4 rounded border-divider"
          />
          <span className="text-sm text-ink/80">Thỏa thuận (không hiển thị mức lương cụ thể)</span>
        </label>
        {!salary.negotiable && (
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="number"
              min={0}
              value={salary.min ?? ""}
              onChange={(e) => setSalary({ min: parseAmount(e.target.value) })}
              placeholder="Từ"
              aria-label="Lương tối thiểu"
              // `!w-40` ghi đè `w-full` của `inputClass` (cùng nhóm width — đánh dấu important để
              // thắng chắc chắn, không phụ thuộc thứ tự Tailwind sinh CSS).
              className={`${inputClass} !w-40`}
            />
            <span className="text-ink/65">–</span>
            <input
              type="number"
              min={0}
              value={salary.max ?? ""}
              onChange={(e) => setSalary({ max: parseAmount(e.target.value) })}
              placeholder="Đến"
              aria-label="Lương tối đa"
              className={`${inputClass} !w-40`}
            />
            <select
              value={salary.currency}
              onChange={(e) => setSalary({ currency: e.target.value === "USD" ? "USD" : "VND" })}
              aria-label="Đơn vị tiền tệ"
              className="w-24 rounded-lg border border-divider px-3 py-2 text-sm text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              <option value="VND">VND</option>
              <option value="USD">USD</option>
            </select>
          </div>
        )}
      </fieldset>

      {/* Mô tả (editor định dạng) */}
      <div className="space-y-1.5">
        <label className={GROUP_LABEL}>
          Mô tả <span className="text-red-500">*</span>
        </label>
        <RichTextEditor
          value={form.description}
          onChange={(html) => set("description", html)}
          ariaLabel="Mô tả công việc"
        />
        <p className="text-xs text-ink/65">
          Dán được cả khối; định dạng bằng thanh công cụ (đậm/nghiêng/gạch chân/danh sách).
        </p>
      </div>

      {/* Yêu cầu (editor định dạng — dán cả khối) */}
      <div className="space-y-1.5">
        <label className={GROUP_LABEL}>Yêu cầu</label>
        <RichTextEditor
          value={form.requirements}
          onChange={(html) => set("requirements", html)}
          ariaLabel="Yêu cầu ứng viên"
        />
        <p className="text-xs text-ink/65">Dán cả danh sách yêu cầu; định dạng tùy ý.</p>
      </div>

      {/* Quyền lợi (editor định dạng) */}
      <div className="space-y-1.5">
        <label className={GROUP_LABEL}>Quyền lợi</label>
        <RichTextEditor
          value={form.benefits}
          onChange={(html) => set("benefits", html)}
          ariaLabel="Quyền lợi"
        />
      </div>

      <div className="flex items-center gap-3 border-t border-divider pt-4">
        <button
          type="submit"
          disabled={submitting}
          className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
        >
          {submitting ? "Đang lưu…" : submitLabel}
        </button>
      </div>
    </form>
  );
}
