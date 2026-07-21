"use client";

import { useState } from "react";
import type { JobPostingInput, SalaryInfo } from "@ars/shared-types";
import { RichTextEditor } from "@/components/RichTextEditor";
import { EMPLOYMENT_TYPE_OPTIONS, LEVEL_OPTIONS } from "@/lib/jobs";

// JD-2a: JobForm CHỈ còn màn "Tin tuyển dụng" (field posting — ứng viên thấy). Rubric + câu hỏi sàng lọc
// dời sang màn "Cấu hình sàng lọc" (ScreeningConfigForm, trên JD đã lưu); gate dời ra danh sách JD.
// rubric/screener_questions/gate_config đi XUYÊN QUA từ `initial` (không sửa ở màn này) — được làm sạch
// khi submit để không gửi item rỗng (JobPostingCreate validate criterion non-empty).

const INPUT =
  "w-full min-h-9 rounded-lg border-2 border-ink/55 bg-surface px-2.5 py-1.5 text-sm text-ink placeholder:text-ink/55 hover:border-ink/70 focus-visible:border-accent focus-visible:outline-none";
const LABEL = "mb-1.5 block text-xs font-semibold text-ink/70";

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
      {(localError || errorMsg) && (
        <p className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          {localError ?? errorMsg}
        </p>
      )}
      {warning && (
        <p className="rounded-lg border border-orange-200 bg-orange-50 px-4 py-2 text-sm text-orange-800">
          {warning}
        </p>
      )}

      {/* Tiêu đề */}
      <div className="space-y-1.5">
        <label htmlFor="jd-title" className={LABEL}>
          Tiêu đề <span className="text-red-500">*</span>
        </label>
        <input
          id="jd-title"
          type="text"
          value={form.title}
          onChange={(e) => set("title", e.target.value)}
          placeholder="vd: Backend Intern (Node.js)"
          className={INPUT}
        />
      </div>

      {/* Cấp bậc + loại việc */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <label htmlFor="jd-level" className={LABEL}>
            Cấp bậc
          </label>
          <select
            id="jd-level"
            value={form.level ?? ""}
            onChange={(e) => set("level", e.target.value || null)}
            className={INPUT}
          >
            <option value="">— Chọn cấp bậc —</option>
            {LEVEL_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1.5">
          <label htmlFor="jd-emptype" className={LABEL}>
            Loại công việc
          </label>
          <select
            id="jd-emptype"
            value={form.employment_type ?? ""}
            onChange={(e) => set("employment_type", e.target.value || null)}
            className={INPUT}
          >
            <option value="">— Chọn loại việc —</option>
            {EMPLOYMENT_TYPE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
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
              className="w-40 rounded-lg border border-divider px-3 py-2 text-sm text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            />
            <span className="text-ink/65">–</span>
            <input
              type="number"
              min={0}
              value={salary.max ?? ""}
              onChange={(e) => setSalary({ max: parseAmount(e.target.value) })}
              placeholder="Đến"
              aria-label="Lương tối đa"
              className="w-40 rounded-lg border border-divider px-3 py-2 text-sm text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
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
        <label className={LABEL}>
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
        <label className={LABEL}>Yêu cầu</label>
        <RichTextEditor
          value={form.requirements}
          onChange={(html) => set("requirements", html)}
          ariaLabel="Yêu cầu ứng viên"
        />
        <p className="text-xs text-ink/65">Dán cả danh sách yêu cầu; định dạng tùy ý.</p>
      </div>

      {/* Quyền lợi (editor định dạng) */}
      <div className="space-y-1.5">
        <label className={LABEL}>Quyền lợi</label>
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
