import type { ScreenerAnswer } from "@ars/shared-types";

// Khối hiển thị câu trả lời sàng lọc cho HR (08b, PRD §7.3 · §11). THUẦN presentational.
// Ẩn khi chưa/không có câu trả lời (ứng viên chưa nộp form hoặc ca không qua screener).
export function ScreenerAnswers({ answers }: { answers: ScreenerAnswer[] }) {
  if (!answers || answers.length === 0) return null;
  return (
    <div className="space-y-2 rounded-md border border-slate-200 bg-slate-50 px-4 py-3">
      <p className="text-sm font-semibold text-slate-700">Câu trả lời sàng lọc</p>
      <ol className="space-y-2">
        {answers.map((qa, i) => (
          <li key={i} className="text-sm">
            <p className="font-medium text-slate-800">{qa.question}</p>
            <p className="mt-0.5 whitespace-pre-line text-slate-600">
              {qa.answer?.trim() || "(không trả lời)"}
            </p>
          </li>
        ))}
      </ol>
    </div>
  );
}
