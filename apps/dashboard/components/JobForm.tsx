"use client";

import { useState } from "react";
import type { JobPostingInput, RubricCriterion } from "@ars/shared-types";
import { isWeightBalanced, WEIGHT_TARGET, weightSum } from "@/lib/jobs";

const INPUT =
  "w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500";
const LABEL = "block text-sm font-medium text-slate-700";

function clamp01(n: number): number {
  if (!Number.isFinite(n)) return 0;
  return Math.min(1, Math.max(0, n));
}

// Danh sách text động (dùng chung requirements + screener_questions).
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

  const setRubric = (i: number, patch: Partial<RubricCriterion>) =>
    set(
      "rubric",
      form.rubric.map((c, j) => (j === i ? { ...c, ...patch } : c)),
    );

  const sum = weightSum(form.rubric);
  const balanced = isWeightBalanced(form.rubric);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (submitting) return; // chống double-submit
    const cleaned: JobPostingInput = {
      title: form.title.trim(),
      description: form.description.trim(),
      requirements: form.requirements.map((s) => s.trim()).filter(Boolean),
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

      {/* Tiêu đề + mô tả */}
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

      <div className="space-y-1.5">
        <label htmlFor="jd-desc" className={LABEL}>
          Mô tả <span className="text-red-500">*</span>
        </label>
        <textarea
          id="jd-desc"
          value={form.description}
          onChange={(e) => set("description", e.target.value)}
          rows={4}
          placeholder="Mô tả công việc, bối cảnh, trách nhiệm chính…"
          className={INPUT}
        />
      </div>

      {/* Yêu cầu (danh sách động) */}
      <div className="space-y-1.5">
        <label className={LABEL}>Yêu cầu</label>
        <StringList
          items={form.requirements}
          onChange={(next) => set("requirements", next)}
          placeholder="vd: Node.js + Express"
          addLabel="Thêm yêu cầu"
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
