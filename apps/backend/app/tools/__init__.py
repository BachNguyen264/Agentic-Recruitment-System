"""Placeholder cho tool tự trị của agent (PRD §7 — phase sau).

Mỗi agent sẽ tự quyết dùng tool nào (function calling) nhưng bị giới hạn số bước (PRD §5 trụ cột 2):
- parser:   bộ đọc PDF/DOCX (PyMuPDF/python-docx)
- ranker:   truy vấn vector Qdrant + công cụ chấm điểm rubric
- screener: LLM diễn đạt lời mời + chuẩn hóa câu trả lời (hỏi lại tối đa 1 lần)
- scheduler: gửi email + tạo Google Calendar

Scaffold: KHÔNG triển khai (ENABLE_LLM=false).
"""
