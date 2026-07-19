"use client";

import Underline from "@tiptap/extension-underline";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";

// Editor định dạng NHẸ (JD-1) — chỉ bold/italic/underline/list. Tiptap headless + StarterKit
// (tắt heading/codeBlock/blockquote/hr để giữ định dạng cơ bản, tránh phình UX). CHỈ dùng ở form
// JD (khu HR đã đăng nhập) — /apply chỉ render HTML đã sanitize, KHÔNG kéo editor vào bundle công khai.
// Giá trị = HTML; editor rỗng → phát "" (để check "bắt buộc" ở form còn đúng, không lưu "<p></p>").

function ToolbarButton({
  active,
  onClick,
  title,
  children,
}: {
  active: boolean;
  onClick: () => void;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      aria-pressed={active}
      // mousedown preventDefault: giữ selection trong editor khi bấm nút (không blur).
      onMouseDown={(e) => e.preventDefault()}
      onClick={onClick}
      className={`min-w-[1.75rem] rounded px-2 py-1 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500 ${
        active ? "bg-slate-200 text-slate-900" : "text-slate-600 hover:bg-slate-100"
      }`}
    >
      {children}
    </button>
  );
}

export function RichTextEditor({
  value,
  onChange,
  ariaLabel,
}: {
  value: string;
  onChange: (html: string) => void;
  ariaLabel?: string;
}) {
  const editor = useEditor({
    // Next 14 SSR: KHÔNG render ngay khi khởi tạo (tránh hydration mismatch của contenteditable).
    immediatelyRender: false,
    extensions: [
      StarterKit.configure({
        heading: false,
        codeBlock: false,
        blockquote: false,
        horizontalRule: false,
      }),
      Underline,
    ],
    content: value || "",
    editorProps: {
      attributes: {
        class: "rte-content",
        role: "textbox",
        "aria-multiline": "true",
        ...(ariaLabel ? { "aria-label": ariaLabel } : {}),
      },
    },
    onUpdate: ({ editor }) => {
      // Editor rỗng (chỉ "<p></p>") → phát "" để form "bắt buộc" + backend min_length còn nghĩa.
      onChange(editor.getText().trim() === "" ? "" : editor.getHTML());
    },
  });

  return (
    <div className="rte rounded-md border border-slate-300 focus-within:ring-2 focus-within:ring-slate-500">
      <div className="flex flex-wrap items-center gap-1 border-b border-slate-200 px-2 py-1.5">
        {editor && (
          <>
            <ToolbarButton
              active={editor.isActive("bold")}
              onClick={() => editor.chain().focus().toggleBold().run()}
              title="Đậm"
            >
              <span className="font-bold">B</span>
            </ToolbarButton>
            <ToolbarButton
              active={editor.isActive("italic")}
              onClick={() => editor.chain().focus().toggleItalic().run()}
              title="Nghiêng"
            >
              <span className="italic">I</span>
            </ToolbarButton>
            <ToolbarButton
              active={editor.isActive("underline")}
              onClick={() => editor.chain().focus().toggleUnderline().run()}
              title="Gạch chân"
            >
              <span className="underline">U</span>
            </ToolbarButton>
            <span className="mx-1 h-4 w-px bg-slate-200" aria-hidden />
            <ToolbarButton
              active={editor.isActive("bulletList")}
              onClick={() => editor.chain().focus().toggleBulletList().run()}
              title="Gạch đầu dòng"
            >
              • Danh sách
            </ToolbarButton>
            <ToolbarButton
              active={editor.isActive("orderedList")}
              onClick={() => editor.chain().focus().toggleOrderedList().run()}
              title="Danh sách đánh số"
            >
              1. Đánh số
            </ToolbarButton>
          </>
        )}
      </div>
      <EditorContent editor={editor} className="text-sm text-slate-900" />
    </div>
  );
}
