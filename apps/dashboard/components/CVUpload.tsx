"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import type { ParseCvResponse } from "@ars/shared-types";
import { CVFilePicker } from "@/components/CVFilePicker";
import { btn } from "@/components/ui";
import { parseCv } from "@/lib/api";

// Lo chọn + phân tích CV (dùng ở /cv-check). Chọn file qua CVFilePicker (tái dùng với /apply),
// bấm để gọi LLM bóc tách. Kết quả đẩy lên cha qua onResult để render.
//
// Ba trạng thái loại trừ nhau (khớp thiết kế): CHƯA CHỌN/chưa chạy → dòng mời chọn; ĐANG CHẠY →
// không hiện dòng nào (nút đã tự nói "Đang phân tích…"); CÓ KẾT QUẢ → cha render kết quả.
export function CVUpload({ onResult }: { onResult: (r: ParseCvResponse | null) => void }) {
  const [file, setFile] = useState<File | null>(null);

  const mutation = useMutation({
    mutationFn: parseCv,
    onSuccess: (r) => onResult(r),
  });

  const idle = !mutation.isPending && !mutation.isSuccess;

  return (
    <section aria-busy={mutation.isPending}>
      <CVFilePicker
        onFile={(f) => {
          mutation.reset();
          onResult(null); // chọn file mới → bỏ kết quả cũ (đừng để kết quả CV trước nằm lại)
          setFile(f);
        }}
        disabled={mutation.isPending}
        hint="Chỉ .pdf / .docx · tối đa 10MB · không lưu trữ"
      />

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => file && mutation.mutate(file)}
          disabled={!file || mutation.isPending}
          className={btn("primary")}
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
            <circle cx="11" cy="11" r="8" />
            <path d="m21 21-4.3-4.3" />
          </svg>
          {mutation.isPending ? "Đang phân tích…" : "Phân tích CV"}
        </button>
        {mutation.isPending && (
          // role="status": chờ LLM mất vài giây, trình đọc màn hình phải được báo là đang chạy —
          // nhãn nút đã disabled thường không được đọc lại.
          <span role="status" className="text-[13px] text-ink/65">
            Đang gọi mô hình để bóc tách, chờ vài giây…
          </span>
        )}
      </div>

      {idle && (
        <p className="mt-4 text-[13px] text-ink/65">
          Chưa có kết quả — chọn một CV rồi bấm “Phân tích CV”.
        </p>
      )}

      {mutation.isError && (
        <p
          role="alert"
          className="mt-3 rounded-xl border-2 border-red-200 bg-red-50 px-4 py-2.5 text-[13px] text-red-700"
        >
          Không phân tích được CV. {String((mutation.error as Error)?.message)}
        </p>
      )}
    </section>
  );
}
