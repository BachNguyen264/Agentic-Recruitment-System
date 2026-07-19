"use client";

import { useState } from "react";
import type { JobPostingInput, RubricCriterion, SalaryInfo } from "@ars/shared-types";
import { RichTextEditor } from "@/components/RichTextEditor";
import {
  EMPLOYMENT_TYPE_OPTIONS,
  isWeightBalanced,
  LEVEL_OPTIONS,
  WEIGHT_TARGET,
  weightSum,
} from "@/lib/jobs";

const INPUT =
  "w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500";
const LABEL = "block text-sm font-medium text-slate-700";

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

// Danh sách text động (dùng cho screener_questions — yêu cầu đã chuyển sang editor định dạng ở JD-1).
function StringList({
  items,
  onChange,
  placeholder,
  addLabel,
}: {
  items: string[];
  onChange: (next: string[]) => void;
  placeholder: string;
  addLabel: string;
}) {
  return (
    <div className="space-y-2">
      {items.map((val, i) => (
        <div key={i} className="flex items-center gap-2">
          <input
            type="text"
            value={val}
            placeholder={placeholder}
            onChange={(e) => onChange(items.map((x, j) => (j === i ? e.target.value : x)))}
            className={INPUT}
          />
          <button
            type="button"
            onClick={() => onChange(items.filter((_, j) => j !== i))}
            aria-label="Xóa dòng"
            className="shrink-0 rounded-md border border-slate-200 px-2.5 py-2 text-sm text-slate-500 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500"
          >
            ✕
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={() => onChange([...items, ""])}
        className="text-sm font-medium text-slate-600 hover:text-slate-900"
      >
        + {addLabel}
      </button>
    </div>
  );
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

  const setRubric = (i: number, patch: Partial<RubricCriterion>) =>
    set(
      "rubric",
      form.rubric.map((c, j) => (j === i ? { ...c, ...patch } : c)),
    );

  const sum = weightSum(form.rubric);
  const balanced = isWeightBalanced(form.rubric);
  const salary = form.salary;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (submitting) return; // chống double-submit

    // Lương: thỏa thuận → bỏ min/max; ngược lại min ≤ max (báo lỗi inline, backend cũng validate).
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
        <p className="rounded-md border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          {localError ?? errorMsg}
        </p>
      )}
      {warning && (
        <p className="rounded-md border border-orange-200 bg-orange-50 px-4 py-2 text-sm text-orange-800">
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
      <fieldset className="space-y-3 rounded-md border border-slate-200 p-4">
        <legend className="px-1 text-sm font-medium text-slate-700">Lương</legend>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={salary.negotiable}
            onChange={(e) => setSalary({ negotiable: e.target.checked })}
            className="h-4 w-4 rounded border-slate-300"
          />
          <span className="text-sm text-slate-700">Thỏa thuận (không hiển thị mức lương cụ thể)</span>
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
              className="w-40 rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500"
            />
            <span className="text-slate-400">–</span>
            <input
              type="number"
              min={0}
              value={salary.max ?? ""}
              onChange={(e) => setSalary({ max: parseAmount(e.target.value) })}
              placeholder="Đến"
              aria-label="Lương tối đa"
              className="w-40 rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500"
            />
            <select
              value={salary.currency}
              onChange={(e) => setSalary({ currency: e.target.value === "USD" ? "USD" : "VND" })}
              aria-label="Đơn vị tiền tệ"
              className="w-24 rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500"
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
        <p className="text-xs text-slate-400">
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
        <p className="text-xs text-slate-400">Dán cả danh sách yêu cầu; định dạng tùy ý.</p>
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

      {/* Rubric (danh sách động — tiêu chí + trọng số) */}
      <div className="space-y-2">
        <div className="flex items-baseline justify-between">
          <label className={LABEL}>Rubric chấm điểm (HR tự nhập)</label>
          <span className={`text-xs ${balanced ? "text-slate-400" : "text-amber-600"}`}>
            Tổng trọng số: <span className="font-semibold">{sum.toFixed(2)}</span>
            {!balanced && ` (nên ≈ ${WEIGHT_TARGET.toFixed(1)})`}
          </span>
        </div>
        <div className="space-y-2">
          {form.rubric.map((c, i) => (
            <div key={i} className="flex items-center gap-2">
              <input
                type="text"
                value={c.criterion}
                placeholder="Tiêu chí, vd: Kinh nghiệm Node.js"
                onChange={(e) => setRubric(i, { criterion: e.target.value })}
                className={INPUT}
              />
              <input
                type="number"
                min={0}
                max={1}
                step={0.05}
                value={c.weight}
                aria-label={`Trọng số tiêu chí ${i + 1}`}
                onChange={(e) => setRubric(i, { weight: clamp01(parseFloat(e.target.value)) })}
                className="w-24 shrink-0 rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500"
              />
              <button
                type="button"
                onClick={() => set("rubric", form.rubric.filter((_, j) => j !== i))}
                aria-label="Xóa tiêu chí"
                className="shrink-0 rounded-md border border-slate-200 px-2.5 py-2 text-sm text-slate-500 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500"
              >
                ✕
              </button>
            </div>
          ))}
          <button
            type="button"
            onClick={() => set("rubric", [...form.rubric, { criterion: "", weight: 0 }])}
            className="text-sm font-medium text-slate-600 hover:text-slate-900"
          >
            + Thêm tiêu chí
          </button>
        </div>
        <p className="text-xs text-slate-400">
          Trọng số 0–1. Tổng nên ≈ 1.0 (không bắt buộc — ranker chuẩn hóa lại theo trọng số).
        </p>
      </div>

      {/* Câu hỏi sàng lọc (danh sách động) */}
      <div className="space-y-1.5">
        <label className={LABEL}>Câu hỏi sàng lọc</label>
        <StringList
          items={form.screener_questions}
          onChange={(next) => set("screener_questions", next)}
          placeholder="vd: Mức lương kỳ vọng?"
          addLabel="Thêm câu hỏi"
        />
        <p className="text-xs text-slate-400">Dùng cho vòng Screener (kích hoạt sau — PRD §10).</p>
      </div>

      {/* Gate (nợ từ 03c) */}
      <fieldset className="space-y-3 rounded-md border border-slate-200 bg-slate-50 p-4">
        <legend className="px-1 text-sm font-medium text-slate-700">Gate tự động (PRD §9)</legend>
        <label className="flex items-start gap-3">
          <input
            type="checkbox"
            checked={form.gate_config.auto_reject}
            onChange={(e) =>
              set("gate_config", { ...form.gate_config, auto_reject: e.target.checked })
            }
            className="mt-0.5 h-4 w-4 rounded border-slate-300"
          />
          <span className="text-sm">
            <span className="font-medium text-slate-800">Auto-từ-chối</span>
            <span className="block text-slate-500">
              Tự động từ chối ca điểm thấp RÕ RÀNG (tự tin, không cờ) + gửi thư từ chối. Ca bất định
              vẫn về HR. Mặc định TẮT.
            </span>
          </span>
        </label>
        <label className="flex items-start gap-3">
          <input
            type="checkbox"
            checked={form.gate_config.auto_invite}
            onChange={(e) =>
              set("gate_config", { ...form.gate_config, auto_invite: e.target.checked })
            }
            className="mt-0.5 h-4 w-4 rounded border-slate-300"
          />
          <span className="text-sm">
            <span className="font-medium text-slate-800">Auto-mời</span>
            <span className="block text-slate-500">
              Tự động mời ca ĐẠT + đã trả lời sàng lọc (tự tin, không cờ) + gửi thư mời. Ca bất định /
              không phản hồi vẫn về HR. Mặc định TẮT.
            </span>
          </span>
        </label>
      </fieldset>

      <div className="flex items-center gap-3 border-t border-slate-200 pt-4">
        <button
          type="submit"
          disabled={submitting}
          className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500 disabled:opacity-50"
        >
          {submitting ? "Đang lưu…" : submitLabel}
        </button>
      </div>
    </form>
  );
}
