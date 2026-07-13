"use client";

import { useRef, useState } from "react";

export const ALLOWED_EXT = [".pdf", ".docx"];
export const MAX_BYTES = 10 * 1024 * 1024; // 10MB (khớp cv_storage.MAX_BYTES ở backend)

export function validateCvFile(file: File): string | null {
  const name = file.name.toLowerCase();
  if (!ALLOWED_EXT.some((ext) => name.endsWith(ext))) return "Chỉ nhận file .pdf hoặc .docx.";
  if (file.size > MAX_BYTES) return "File quá lớn (tối đa 10MB).";
  return null;
}

// Dropzone chọn CV (kéo-thả + bấm) + validate client. Thuần presentational: emit file hợp lệ qua
// onFile (null khi xóa/không hợp lệ) để cha hành động — phân tích (cv-check) hoặc nộp (apply).
// Tách từ CVUpload (01b) để tái dùng ở form nộp công khai (07). Server VẪN validate lại (magic bytes).
export function CVFilePicker({
  onFile,
  disabled = false,
}: {
  onFile: (file: File | null) => void;
  disabled?: boolean;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  function select(f: File | null) {
    if (!f) {
      setFile(null);
      setError(null);
      onFile(null);
      return;
    }
    const err = validateCvFile(f);
    if (err) {
      setFile(null);
      setError(err);
      onFile(null);
      return;
    }
    setError(null);
    setFile(f);
    onFile(f);
  }

  return (
    <div className="space-y-2">
      <div
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-disabled={disabled}
        aria-label="Chọn file CV (.pdf hoặc .docx)"
        onClick={() => !disabled && inputRef.current?.click()}
        onKeyDown={(e) => {
          if (!disabled && (e.key === "Enter" || e.key === " ")) inputRef.current?.click();
        }}
        onDragOver={(e) => {
          if (disabled) return;
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          if (disabled) return;
          e.preventDefault();
          setDragging(false);
          select(e.dataTransfer.files?.[0] ?? null);
        }}
        className={`flex flex-col items-center justify-center rounded-md border-2 border-dashed px-4 py-8 text-center transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500 ${
          disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer"
        } ${dragging ? "border-slate-900 bg-slate-100" : "border-slate-300 bg-white hover:bg-slate-50"}`}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.docx"
          className="hidden"
          disabled={disabled}
          onChange={(e) => select(e.target.files?.[0] ?? null)}
        />
        <p className="text-sm font-medium text-slate-700">Kéo-thả CV vào đây, hoặc bấm để chọn</p>
        <p className="mt-1 text-xs text-slate-400">Chỉ .pdf / .docx · tối đa 10MB</p>
        {file && (
          <p className="mt-3 text-sm text-slate-800">
            Đã chọn: <span className="font-medium">{file.name}</span>
          </p>
        )}
      </div>
      {error && (
        <p className="rounded-md border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          {error}
        </p>
      )}
    </div>
  );
}
