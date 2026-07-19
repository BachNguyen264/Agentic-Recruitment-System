"use client";

import DOMPurify from "dompurify";
import { useEffect, useState } from "react";

// Render HTML định dạng (JD-1) AN TOÀN trên trang CÔNG KHAI /apply. Nội dung do HR soạn (rủi ro thấp)
// nhưng /apply là trang guest → SANITIZE bằng DOMPurify là chuẩn (không xuất HTML thô).
// Sanitize CHỈ ở client (useEffect): tránh cần DOM khi SSR; dữ liệu /apply vốn fetch client-side nên
// không mất nội dung khi render lần đầu. Chỉ cho phép thẻ định dạng cơ bản, KHÔNG thuộc tính (chặn
// on*/style/href injection). script/iframe/img... đều bị loại.
const ALLOWED_TAGS = ["p", "br", "strong", "b", "em", "i", "u", "ul", "ol", "li"];
const ALLOWED_ATTR: string[] = [];

export function SafeHtml({ html, className }: { html: string; className?: string }) {
  const [clean, setClean] = useState("");

  useEffect(() => {
    setClean(DOMPurify.sanitize(html ?? "", { ALLOWED_TAGS, ALLOWED_ATTR }));
  }, [html]);

  if (!clean) return null; // rỗng / chưa sanitize xong → không render gì
  return <div className={className} dangerouslySetInnerHTML={{ __html: clean }} />;
}
