"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import type { ScreenerForm } from "@ars/shared-types";
import { getScreener, submitScreener } from "@/lib/api";

// Trang trả lời sàng lọc (magic-link, PRD §7.3, §10). Ứng viên guest: chỉ thấy CÂU HỎI + tiêu đề JD
// (KHÔNG rubric/điểm). Token sai/hết hạn/đã nộp → thông báo tương ứng (không form). Chống double-submit.
export default function ScreeningPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;

  const formQuery = useQuery<ScreenerForm>({
    queryKey: ["screener", token],
    queryFn: () => getScreener(token),
    enabled: Boolean(token),
    retry: false, // token sai/hết hạn/đã nộp → lỗi, đừng retry.
  });

  const [answers, setAnswers] = useState<Record<number, string>>({});
  const questions = formQuery.data?.questions ?? [];

  const mutation = useMutation({
    mutationFn: () => submitScreener(token, questions.map((_, i) => answers[i] ?? "")),
  });

  // ── Màn xác nhận (sau khi nộp thành công) — KHÔNG hiện điểm/trạng thái ──
  if (mutation.isSuccess) {
    return (
      <main className="mx-auto max-w-2xl p-6 sm:p-8">
        <div className="rounded-md border border-green-200 bg-green-50 px-6 py-10 text-center">
          <p className="text-lg font-semibold text-green-800">Cảm ơn bạn! 🎉</p>
          <p className="mx-auto mt-2 max-w-md text-sm text-green-700">
            Câu trả lời của bạn đã được ghi nhận. Bộ phận Tuyển dụng sẽ xem xét và liên hệ với bạn
            qua email.
          </p>
        </div>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-2xl space-y-6 p-6 sm:p-8">
      {formQuery.isLoading && <p className="text-sm text-slate-500">Đang tải câu hỏi…</p>}

      {/* Token sai/hết hạn/đã nộp → backend trả message rõ; hiện thông báo, KHÔNG form. */}
      {formQuery.isError && (
        <div className="rounded-md border border-slate-200 bg-white px-6 py-10 text-center">
          <p className="text-sm font-medium text-slate-700">
            {String((formQuery.error as Error)?.message) || "Liên kết không hợp lệ."}
          </p>
          <p className="mt-2 text-xs text-slate-400">
            Nếu bạn cho rằng đây là nhầm lẫn, vui lòng liên hệ bộ phận Tuyển dụng.
          </p>
        </div>
      )}

      {formQuery.data && (
        <>
          <header className="space-y-1">
            <h1 className="text-2xl font-bold text-slate-900">Câu hỏi sàng lọc</h1>
            <p className="text-sm text-slate-500">
              Vị trí: <span className="font-medium text-slate-700">{formQuery.data.job_title}</span>. Vui
              lòng trả lời các câu hỏi dưới đây để tiếp tục quy trình.
            </p>
          </header>

          {questions.length === 0 ? (
            <p className="text-sm text-slate-500">Không có câu hỏi bổ sung.</p>
          ) : (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (!mutation.isPending) mutation.mutate();
              }}
              className="space-y-5"
            >
              {questions.map((q, i) => (
                <div key={i} className="space-y-1.5">
                  <label htmlFor={`q-${i}`} className="block text-sm font-medium text-slate-700">
                    {i + 1}. {q}
                  </label>
                  <textarea
                    id={`q-${i}`}
                    rows={2}
                    value={answers[i] ?? ""}
                    onChange={(e) => setAnswers((prev) => ({ ...prev, [i]: e.target.value }))}
                    className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500 disabled:bg-slate-50"
                    disabled={mutation.isPending}
                    maxLength={5000}
                  />
                </div>
              ))}

              {mutation.isError && (
                <p className="rounded-md border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
                  {String((mutation.error as Error)?.message) ||
                    "Không gửi được câu trả lời. Vui lòng thử lại."}
                </p>
              )}

              <button
                type="submit"
                disabled={mutation.isPending}
                className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500 disabled:opacity-50"
              >
                {mutation.isPending ? "Đang gửi…" : "Gửi câu trả lời"}
              </button>
            </form>
          )}
        </>
      )}
    </main>
  );
}
