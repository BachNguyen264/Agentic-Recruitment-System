"use client";

import { useMutation } from "@tanstack/react-query";
import { useRef, useState } from "react";
import type { ParseCvResponse } from "@ars/shared-types";
import { parseCv } from "@/lib/api";

const ALLOWED_EXT = [".pdf", ".docx"];
const MAX_BYTES = 10 * 1024 * 1024; // 10MB

function validate(file: File): string | null {
  const name = file.name.toLowerCase();
  if (!ALLOWED_EXT.some((ext) => name.endsWith(ext))) {
    return "Chỉ nhận file .pdf hoặc .docx.";
  }
  if (file.size > MAX_BYTES) {
    return "File quá lớn (tối đa 10MB).";
  }
  return null;
}

// Lo upload + trạng thái (validate/loading/lỗi). Kết quả đẩy lên cha qua onResult để render.
export function CVUpload({ onResult }: { onResult: (r: ParseCvResponse | null) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const mutation = useMutation({
    mutationFn: parseCv,
    onSuccess: (r) => onResult(r),
  });

  function selectFile(f: File | null) {
    mutation.reset();
    onResult(null); // reset kết quả cũ khi chọn file mới
    if (!f) {
      setFile(null);
      setLocalError(null);
      return;
    }
    const err = validate(f);
    if (err) {
      setFile(null);
      setLocalError(err);
      return;
    }
    setLocalError(null);
    setFile(f);
  }

  const errorMsg = localError ?? (mutation.isError ? String((mutation.error as Error)?.message) : null);

  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold">Tải CV lên</h2>

      <div
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") inputRef.current?.click();
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          selectFile(e.dataTransfer.files?.[0] ?? null);
        }}
        className={`flex cursor-pointer flex-col items-center justify-center rounded-md border-2 border-dashed px-4 py-8 text-center transition-colors ${
          dragging ? "border-slate-900 bg-slate-100" : "border-slate-300 bg-white hover:bg-slate-50"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.docx"
          className="hidden"
          onChange={(e) => selectFile(e.target.files?.[0] ?? null)}
        />
        <p className="text-sm font-medium text-slate-700">
          Kéo-thả CV vào đây, hoặc bấm để chọn
        </p>
        <p className="mt-1 text-xs text-slate-400">Chỉ .pdf / .docx · tối đa 10MB</p>
        {file && (
          <p className="mt-3 text-sm text-slate-800">
            Đã chọn: <span className="font-medium">{file.name}</span>
          </p>
        )}
      </div>

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

      {errorMsg && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          {localError ? errorMsg : `Lỗi: ${errorMsg} (backend :8000 đã chạy chưa?)`}
        </div>
      )}
    </section>
  );
}
