"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import type { ParseCvResponse } from "@ars/shared-types";
import { CVFilePicker } from "@/components/CVFilePicker";
import { parseCv } from "@/lib/api";

// Lo upload + phân tích CV (dùng ở /cv-check). Chọn file qua CVFilePicker (tái dùng), bấm để gọi
// LLM bóc tách. Kết quả đẩy lên cha qua onResult để render.
export function CVUpload({ onResult }: { onResult: (r: ParseCvResponse | null) => void }) {
  const [file, setFile] = useState<File | null>(null);

  const mutation = useMutation({
    mutationFn: parseCv,
    onSuccess: (r) => onResult(r),
  });

  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold">Tải CV lên</h2>

      <CVFilePicker
        onFile={(f) => {
          mutation.reset();
          onResult(null); // reset kết quả cũ khi chọn file mới
          setFile(f);
        }}
      />

      <div className="flex items-center gap-3">
        <button
          onClick={() => file && mutation.mutate(file)}
          disabled={!file || mutation.isPending}
          className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
        >
          {mutation.isPending ? "Đang phân tích…" : "Phân tích CV"}
        </button>
        {mutation.isPending && (
          <span className="text-sm text-slate-500">Gọi LLM bóc tách, chờ vài giây…</span>
        )}
      </div>

      {mutation.isError && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          Lỗi: {String((mutation.error as Error)?.message)} (backend :8000 đã chạy chưa?)
        </div>
      )}
    </section>
  );
}
