"use client";

import Link from "next/link";
import { useState } from "react";
import type { ParseCvResponse } from "@ars/shared-types";
import { CVUpload } from "@/components/CVUpload";
import { ParsedCVResult } from "@/components/ParsedCVResult";

export default function CvCheckPage() {
  const [result, setResult] = useState<ParseCvResponse | null>(null);

  return (
    <main className="mx-auto max-w-4xl space-y-8 p-8">
      <header className="space-y-1">
        <Link href="/" className="text-sm text-slate-500 hover:underline">
          ← Về dashboard
        </Link>
        <h1 className="text-2xl font-bold">Kiểm tra bóc tách CV</h1>
        <p className="text-sm text-slate-500">
          Upload một CV (PDF/DOCX) để xem Parser (PRD §7.1) trích ra gì — họ tên, kỹ năng, kinh
          nghiệm, học vấn — kèm confidence. Xử lý in-memory, KHÔNG lưu file.
        </p>
      </header>

      <CVUpload onResult={setResult} />

      {result ? (
        <ParsedCVResult
          parsed_data={result.parsed_data}
          confidence={result.confidence}
          uncertainty_flags={result.uncertainty_flags}
          escalation_reason={result.escalation_reason}
        />
      ) : (
        <p className="text-sm text-slate-400">
          Chưa có kết quả — chọn một CV rồi bấm “Phân tích CV”.
        </p>
      )}
    </main>
  );
}
