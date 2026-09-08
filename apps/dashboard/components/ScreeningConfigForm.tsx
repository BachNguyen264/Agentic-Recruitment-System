"use client";

import { useMemo, useState } from "react";
import type { RubricCriterion, SuggestedCriterion } from "@ars/shared-types";
import { btn, inputClass } from "@/components/ui";
import { isValidRubric, isWeightBalanced, WEIGHT_TARGET, weightSum } from "@/lib/jobs";

// JD-2a màn 2 "Cấu hình sàng lọc" (trên JD ĐÃ LƯU): rubric (tiêu chí + trọng số) + câu hỏi sàng lọc.
// Di dời UI rubric + câu-hỏi từ JobForm (05/JD-1), GIỮ hành vi. Nút "Mở JD" ở đây: chặn nếu rubric
// chưa hợp lệ (≥1 tiêu chí, tổng trọng số > 0 — khớp backend). "Lưu cấu hình" chỉ lưu, không mở.
//
// Ô nhập/nút lấy từ `components/ui` (`inputClass`, `btn`) — KHÔNG chép chuỗi class nữa: bản cũ giữ
// hằng `INPUT` sao y `inputClass` và tự viết class cho nút, nên nút ở hai màn JD dày/mỏng khác nút
// ở mọi màn còn lại (`font-medium` vs `font-semibold`, `opacity-50` vs `opacity-45`).

// Nhãn nhóm (không phải nhãn của MỘT ô nhập — xem chú thích ở chỗ dùng).
const GROUP_LABEL = "mb-1.5 block text-xs font-semibold text-ink/70";

// Nút "✕ xoá dòng": viền `ink/55` như ô nhập bên cạnh. `border-divider` (22% mực) chỉ đạt 1.58:1 so
// với nền — chính `inputClass` đã ghi rõ ngưỡng này (WCAG 1.4.11), nút nhỏ nằm sát ô nhập mà dùng
// viền mờ hơn thì trông như không bấm được.
const ROW_BTN =
  "shrink-0 rounded-lg border-2 border-ink/55 px-2.5 py-2 text-sm text-ink/65 hover:bg-surface";

function clamp01(n: number): number {
  if (!Number.isFinite(n)) return 0;
  return Math.min(1, Math.max(0, n));
}

function StringList({
  items,
  onChange,
  placeholder,
  addLabel,
  itemLabel,
}: {
  items: string[];
  onChange: (next: string[]) => void;
  placeholder: string;
  addLabel: string;
  /** Tên đọc được của từng ô, sẽ thành "<itemLabel> 1", "<itemLabel> 2"… */
  itemLabel: string;
}) {
  return (
    <div className="space-y-2">
      {items.map((val, i) => (
        <div key={i} className="flex items-center gap-2">
          <input
            type="text"
            value={val}
            placeholder={placeholder}
            // `placeholder` KHÔNG phải tên đọc được bền vững (biến mất ngay khi gõ chữ đầu tiên, và
            // một số trình đọc màn hình bỏ qua hẳn). Danh sách động không gắn <label htmlFor> được
            // vì id phải sinh theo chỉ số → dùng aria-label đánh số, khớp thứ tự nhìn thấy.
            aria-label={`${itemLabel} ${i + 1}`}
            onChange={(e) => onChange(items.map((x, j) => (j === i ? e.target.value : x)))}
            className={inputClass}
          />
          <button
            type="button"
            onClick={() => onChange(items.filter((_, j) => j !== i))}
            aria-label={`Xoá ${itemLabel.toLowerCase()} ${i + 1}`}
            className={ROW_BTN}
          >
            ✕
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={() => onChange([...items, ""])}
        className="text-sm font-medium text-ink/65 hover:text-ink"
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
  suggestionsRemaining,
  onSuggestRubric,
}: {
  initialRubric: RubricCriterion[];
  initialQuestions: string[];
  status: string; // trạng thái JD hiện tại (ẩn nút Mở nếu đã OPEN)
  onSave: (rubric: RubricCriterion[], questions: string[]) => void;
  onSaveAndOpen: (rubric: RubricCriterion[], questions: string[]) => void;
  saving: boolean;
  opening: boolean;
  errorMsg?: string | null;
  // JD-3: số lượt AI gợi ý còn lại + callback gọi endpoint (trả list tiêu chí đề xuất, throw khi lỗi/hết lượt).
  suggestionsRemaining: number;
  onSuggestRubric: () => Promise<SuggestedCriterion[]>;
}) {
  // Giữ ≥1 dòng để danh sách động không rỗng hẳn (UX nhập liệu).
  const [rubric, setRubric] = useState<RubricCriterion[]>(
    initialRubric.length ? initialRubric : [{ criterion: "", weight: 0 }],
  );
  const [questions, setQuestions] = useState<string[]>(
    initialQuestions.length ? initialQuestions : [""],
  );
  // JD-3: trạng thái nút "AI gợi ý rubric". Lỗi hiện riêng — KHÔNG mất rubric HR đang có (plan §3.3).
  const [suggesting, setSuggesting] = useState(false);
  const [suggestErr, setSuggestErr] = useState<string | null>(null);

  const canSuggest = suggestionsRemaining > 0 && !suggesting;

  async function handleSuggest() {
    setSuggesting(true);
    setSuggestErr(null);
    try {
      const suggested = await onSuggestRubric();
      // ĐIỀN SẴN: thay rubric hiện tại bằng đề xuất để HR CHỈNH trước khi lưu (KHÔNG tự lưu/áp).
      if (suggested.length) {
        setRubric(suggested.map((c) => ({ criterion: c.criterion, weight: c.weight })));
      }
    } catch (e) {
      setSuggestErr(String((e as Error)?.message) || "Không gợi ý được rubric.");
    } finally {
      setSuggesting(false);
    }
  }

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
        // role="alert" như mọi màn khác trong repo: bấm Lưu xong mà hỏng thì người dùng bàn phím /
        // trình đọc màn hình phải NGHE được, không phải tự đoán mà đi tìm.
        <p
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700"
        >
          {errorMsg}
        </p>
      )}

      {/* Rubric (danh sách động — tiêu chí + trọng số) */}
      <div className="space-y-2">
        <div className="flex items-baseline justify-between">
          {/* <p>, KHÔNG phải <label>: đây là tiêu đề của cả NHÓM ô nhập bên dưới, không gắn với một
              ô nào — một <label> không htmlFor và không bọc input chỉ là chữ trang trí, mà trình đọc
              màn hình lại hứa hẹn ngược lại. Tên đọc được của từng ô nằm ở `aria-label` của nó. */}
          <p className={GROUP_LABEL}>
            Rubric chấm điểm (HR tự nhập) <span className="text-red-500">*</span>
          </p>
          <span className={`text-xs ${balanced ? "text-ink/65" : "text-amber-600"}`}>
            Tổng trọng số: <span className="font-semibold">{sum.toFixed(2)}</span>
            {!balanced && ` (nên ≈ ${WEIGHT_TARGET.toFixed(1)})`}
          </span>
        </div>

        {/* JD-3: AI gợi ý rubric — điền sẵn tiêu chí+trọng số từ JD để HR CHỈNH (không tự áp). */}
        <div className="flex flex-wrap items-center gap-3.5 rounded-xl border-2 border-accent bg-accent-100 px-4 py-3">
          <button
            type="button"
            onClick={handleSuggest}
            disabled={!canSuggest}
            title={
              suggestionsRemaining > 0
                ? "AI đọc JD (tiêu đề/mô tả/yêu cầu) → đề xuất tiêu chí + trọng số để bạn chỉnh"
                : "Đã hết lượt gợi ý — sửa nội dung JD rồi lưu để đặt lại"
            }
            className={btn("primary", "flex-none")}
          >
            <svg
              viewBox="0 0 24 24"
              className="h-[15px] w-[15px]"
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden
            >
              <path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z" />
            </svg>
            {suggesting ? "Đang gợi ý…" : "AI gợi ý rubric"}
          </button>
          <span className="min-w-[180px] flex-1 text-[13px] leading-snug text-accent-800">
            {suggestionsRemaining > 0
              ? `Còn ${suggestionsRemaining} lượt gợi ý cho JD này. AI đề xuất — bạn chỉnh trước khi lưu.`
              : "Hết lượt gợi ý cho JD này. Sửa nội dung JD (tiêu đề/mô tả/yêu cầu) rồi lưu để đặt lại."}
          </span>
        </div>
        {suggestErr && (
          <p
            role="alert"
            className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700"
          >
            {suggestErr}
          </p>
        )}

        <div className="space-y-2">
          {rubric.map((c, i) => (
            <div key={i} className="flex items-center gap-2">
              <input
                type="text"
                value={c.criterion}
                placeholder="Tiêu chí, vd: Kinh nghiệm Node.js"
                // Chỉ có placeholder là KHÔNG có tên đọc được (nó biến mất khi vừa gõ). Ô trọng số
                // ngay bên cạnh vốn đã có aria-label — ô tiêu chí bị bỏ sót.
                aria-label={`Tiêu chí ${i + 1}`}
                onChange={(e) => setCrit(i, { criterion: e.target.value })}
                className={inputClass}
              />
              <input
                type="number"
                min={0}
                max={1}
                step={0.05}
                value={c.weight}
                aria-label={`Trọng số tiêu chí ${i + 1}`}
                onChange={(e) => setCrit(i, { weight: clamp01(parseFloat(e.target.value)) })}
                // `!w-24` ghi đè `w-full` của `inputClass` (hai lớp cùng nhóm width — đánh dấu
                // important để thắng chắc chắn, không phụ thuộc thứ tự Tailwind sinh CSS).
                className={`${inputClass} !w-24 shrink-0`}
              />
              <button
                type="button"
                onClick={() => setRubric(rubric.filter((_, j) => j !== i))}
                aria-label={`Xoá tiêu chí ${i + 1}`}
                className={ROW_BTN}
              >
                ✕
              </button>
            </div>
          ))}
          <button
            type="button"
            onClick={() => setRubric([...rubric, { criterion: "", weight: 0 }])}
            className="text-sm font-medium text-ink/65 hover:text-ink"
          >
            + Thêm tiêu chí
          </button>
        </div>
        <p className="text-xs text-ink/65">
          Cần ≥1 tiêu chí + tổng trọng số &gt; 0 để MỞ JD. Tổng nên ≈ 1.0 (ranker tự chuẩn hóa).
        </p>
      </div>

      {/* Câu hỏi sàng lọc (danh sách động) */}
      <div className="space-y-1.5">
        {/* Cũng là tiêu đề NHÓM, không phải nhãn của một ô — xem chú thích ở khối rubric. */}
        <p className={GROUP_LABEL}>Câu hỏi sàng lọc (tùy chọn)</p>
        <StringList
          items={questions}
          onChange={setQuestions}
          placeholder="vd: Mức lương kỳ vọng?"
          addLabel="Thêm câu hỏi"
          itemLabel="Câu hỏi"
        />
        <p className="text-xs text-ink/65">Dùng cho vòng Screener (PRD §10).</p>
      </div>

      <div className="flex flex-wrap items-center gap-3 border-t border-divider pt-4">
        <button
          type="button"
          onClick={() => onSave(cleanRubric, cleanQuestions)}
          disabled={busy}
          className={btn("secondary")}
        >
          {saving ? "Đang lưu…" : "Lưu cấu hình"}
        </button>
        {!isOpen && (
          <button
            type="button"
            onClick={() => onSaveAndOpen(cleanRubric, cleanQuestions)}
            disabled={busy || !rubricOk}
            title={rubricOk ? "Lưu cấu hình và mở JD để nhận CV" : "Cần ≥1 tiêu chí rubric (tổng trọng số > 0) để mở JD"}
            className={btn("primary")}
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
