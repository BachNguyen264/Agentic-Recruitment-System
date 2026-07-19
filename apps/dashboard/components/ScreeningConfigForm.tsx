"use client";

import { useMemo, useState } from "react";
import type { RubricCriterion } from "@ars/shared-types";
import { isValidRubric, isWeightBalanced, WEIGHT_TARGET, weightSum } from "@/lib/jobs";

// JD-2a màn 2 "Cấu hình sàng lọc" (trên JD ĐÃ LƯU): rubric (tiêu chí + trọng số) + câu hỏi sàng lọc.
// Di dời UI rubric + câu-hỏi từ JobForm (05/JD-1), GIỮ hành vi. Nút "Mở JD" ở đây: chặn nếu rubric
// chưa hợp lệ (≥1 tiêu chí, tổng trọng số > 0 — khớp backend). "Lưu cấu hình" chỉ lưu, không mở.

const INPUT =
  "w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500";
const LABEL = "block text-sm font-medium text-slate-700";

function clamp01(n: number): number {
  if (!Number.isFinite(n)) return 0;
  return Math.min(1, Math.max(0, n));
}

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

export function ScreeningConfigForm({
  initialRubric,
  initialQuestions,
  status,
  onSave,
  onSaveAndOpen,
  saving,
  opening,
  errorMsg,
}: {
  initialRubric: RubricCriterion[];
  initialQuestions: string[];
  status: string; // trạng thái JD hiện tại (ẩn nút Mở nếu đã OPEN)
  onSave: (rubric: RubricCriterion[], questions: string[]) => void;
  onSaveAndOpen: (rubric: RubricCriterion[], questions: string[]) => void;
  saving: boolean;
  opening: boolean;
  errorMsg?: string | null;
}) {
  // Giữ ≥1 dòng để danh sách động không rỗng hẳn (UX nhập liệu).
  const [rubric, setRubric] = useState<RubricCriterion[]>(
    initialRubric.length ? initialRubric : [{ criterion: "", weight: 0 }],
  );
  const [questions, setQuestions] = useState<string[]>(
    initialQuestions.length ? initialQuestions : [""],
  );

  const setCrit = (i: number, patch: Partial<RubricCriterion>) =>
    setRubric((r) => r.map((c, j) => (j === i ? { ...c, ...patch } : c)));

  const cleanRubric = useMemo(
    () =>
      rubric
        .map((c) => ({ criterion: c.criterion.trim(), weight: clamp01(c.weight) }))
        .filter((c) => c.criterion.length > 0),
    [rubric],
  );
  const cleanQuestions = useMemo(
    () => questions.map((s) => s.trim()).filter(Boolean),
    [questions],
  );

  const sum = weightSum(rubric);
  const balanced = isWeightBalanced(rubric);
  const rubricOk = isValidRubric(cleanRubric);
  const isOpen = status === "OPEN";
  const busy = saving || opening;

  return (
    <div className="space-y-6">
      {errorMsg && (
        <p className="rounded-md border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          {errorMsg}
        </p>
      )}

      {/* Rubric (danh sách động — tiêu chí + trọng số) */}
      <div className="space-y-2">
        <div className="flex items-baseline justify-between">
          <label className={LABEL}>
            Rubric chấm điểm (HR tự nhập) <span className="text-red-500">*</span>
          </label>
          <span className={`text-xs ${balanced ? "text-slate-400" : "text-amber-600"}`}>
            Tổng trọng số: <span className="font-semibold">{sum.toFixed(2)}</span>
            {!balanced && ` (nên ≈ ${WEIGHT_TARGET.toFixed(1)})`}
          </span>
        </div>
        <div className="space-y-2">
          {rubric.map((c, i) => (
            <div key={i} className="flex items-center gap-2">
              <input
                type="text"
                value={c.criterion}
                placeholder="Tiêu chí, vd: Kinh nghiệm Node.js"
                onChange={(e) => setCrit(i, { criterion: e.target.value })}
                className={INPUT}
              />
              <input
                type="number"
                min={0}
                max={1}
                step={0.05}
                value={c.weight}
                aria-label={`Trọng số tiêu chí ${i + 1}`}
                onChange={(e) => setCrit(i, { weight: clamp01(parseFloat(e.target.value)) })}
                className="w-24 shrink-0 rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500"
              />
              <button
                type="button"
                onClick={() => setRubric(rubric.filter((_, j) => j !== i))}
                aria-label="Xóa tiêu chí"
                className="shrink-0 rounded-md border border-slate-200 px-2.5 py-2 text-sm text-slate-500 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500"
              >
                ✕
              </button>
            </div>
          ))}
          <button
            type="button"
            onClick={() => setRubric([...rubric, { criterion: "", weight: 0 }])}
            className="text-sm font-medium text-slate-600 hover:text-slate-900"
          >
            + Thêm tiêu chí
          </button>
        </div>
        <p className="text-xs text-slate-400">
          Cần ≥1 tiêu chí + tổng trọng số &gt; 0 để MỞ JD. Tổng nên ≈ 1.0 (ranker tự chuẩn hóa).
        </p>
      </div>

      {/* Câu hỏi sàng lọc (danh sách động) */}
      <div className="space-y-1.5">
        <label className={LABEL}>Câu hỏi sàng lọc (tùy chọn)</label>
        <StringList
          items={questions}
          onChange={setQuestions}
          placeholder="vd: Mức lương kỳ vọng?"
          addLabel="Thêm câu hỏi"
        />
        <p className="text-xs text-slate-400">Dùng cho vòng Screener (PRD §10).</p>
      </div>

      <div className="flex flex-wrap items-center gap-3 border-t border-slate-200 pt-4">
        <button
          type="button"
          onClick={() => onSave(cleanRubric, cleanQuestions)}
          disabled={busy}
          className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500 disabled:opacity-50"
        >
          {saving ? "Đang lưu…" : "Lưu cấu hình"}
        </button>
        {!isOpen && (
          <button
            type="button"
            onClick={() => onSaveAndOpen(cleanRubric, cleanQuestions)}
            disabled={busy || !rubricOk}
            title={rubricOk ? "Lưu cấu hình và mở JD để nhận CV" : "Cần ≥1 tiêu chí rubric (tổng trọng số > 0) để mở JD"}
            className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500 disabled:opacity-50"
          >
            {opening ? "Đang mở…" : "Lưu & Mở JD"}
          </button>
        )}
        {isOpen && (
          <span className="text-sm text-green-700">JD đang mở — đã nhận CV ở /apply.</span>
        )}
      </div>
    </div>
  );
}
