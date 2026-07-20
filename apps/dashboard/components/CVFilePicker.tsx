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
  hint = "Chỉ .pdf / .docx · tối đa 10MB",
}: {
  onFile: (file: File | null) => void;
  disabled?: boolean;
  /** Dòng phụ dưới lời mời chọn file. /cv-check nói thêm "không lưu trữ" (đúng — parse trong bộ
   *  nhớ); /apply thì KHÔNG được nói vậy vì hồ sơ nộp lên CÓ lưu. */
  hint?: string;
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
        // Tên nhãn phải ĐỔI THEO trạng thái: aria-label GHI ĐÈ nội dung con, mà tên file bên trong
        // lại là chỉ báo DUY NHẤT rằng đã chọn được file. Để nhãn tĩnh thì người dùng trình đọc màn
        // hình bấm "Phân tích CV" mà không có cách nào biết đang phân tích file nào.
        aria-label={
          file
            ? `Đã chọn ${file.name}. Bấm để chọn file CV khác.`
            : "Chọn file CV (.pdf hoặc .docx)"
        }
        onClick={() => !disabled && inputRef.current?.click()}
        onKeyDown={(e) => {
          if (disabled) return;
          if (e.key === "Enter") inputRef.current?.click();
          // Space: chặn mặc định (nếu không trang vừa mở hộp thoại chọn file VỪA cuộn xuống),
          // rồi kích hoạt ở keyup như hành vi chuẩn của <button>.
          if (e.key === " ") e.preventDefault();
        }}
        onKeyUp={(e) => {
          if (!disabled && e.key === " ") inputRef.current?.click();
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
        className={`flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-4 py-7 text-center transition-colors ${
          disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer"
        } ${
          dragging
            ? "border-accent bg-accent-100"
            : "border-divider bg-surface hover:border-ink/40"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.docx"
          className="hidden"
          disabled={disabled}
          onChange={(e) => select(e.target.files?.[0] ?? null)}
        />

        <svg
          viewBox="0 0 24 24"
          className="h-[26px] w-[26px] text-ink/45"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.8}
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden
        >
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="17 8 12 3 7 8" />
          <line x1="12" x2="12" y1="3" y2="15" />
        </svg>

        {/* Đã chọn file → tên file THAY CHO lời mời chọn (khớp thiết kế): trạng thái hiện tại quan
            trọng hơn hướng dẫn đã dùng xong. Vẫn bấm/thả lại được để đổi file. */}
        <p className="mt-2 break-all text-[13px] font-semibold">
          {file ? file.name : "Kéo-thả CV vào đây, hoặc bấm để chọn"}
        </p>
        <p className="mt-1 text-xs text-ink/45">{file ? "Bấm để chọn file khác" : hint}</p>
      </div>

      {error && (
        <p
          role="alert"
          className="rounded-xl border-2 border-red-200 bg-red-50 px-4 py-2.5 text-[13px] text-red-700"
        >
          {error}
        </p>
      )}
    </div>
  );
}
