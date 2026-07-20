import type { ScreenerAnswer } from "@ars/shared-types";

// Khối hiển thị câu trả lời sàng lọc cho HR (08b, PRD §7.3 · §11). THUẦN presentational.
// Ẩn khi chưa/không có câu trả lời (ứng viên chưa nộp form hoặc ca không qua screener).
export function ScreenerAnswers({ answers }: { answers: ScreenerAnswer[] }) {
  if (!answers || answers.length === 0) return null;
  return (
    <section className="rounded-xl border-2 border-divider bg-surface p-4">
      <h2 className="mb-2.5 font-heading text-[15px] font-bold">Câu trả lời sàng lọc</h2>
      <ol>
        {answers.map((qa, i) => (
          <li key={i} className="border-t border-divider py-2">
            <p className="text-[13px] font-semibold">{qa.question}</p>
            <p className="mt-0.5 whitespace-pre-line text-[13px] text-ink/70">
              {qa.answer?.trim() || "(không trả lời)"}
            </p>
          </li>
        ))}
      </ol>
    </section>
  );
}
