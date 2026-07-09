"""ParsedCV — đầu ra có cấu trúc của Parser (PRD §7.1).

Dùng làm schema cho LLM structured output (ChatOpenAI.with_structured_output). Giữ ĐƠN GIẢN:
chỉ những trường cần cho Ranker/ReviewCard ở phase sau (PRD §16 parsed_data). Field description
là phần hướng dẫn LLM trích xuất — chỉ trích thông tin CÓ THẬT trong CV, trường thiếu để None.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Experience(BaseModel):
    company: str | None = Field(None, description="Tên công ty / tổ chức.")
    title: str | None = Field(None, description="Chức danh / vị trí đảm nhận.")
    duration: str | None = Field(None, description="Khoảng thời gian, vd '2020–2023' hoặc '2 năm'.")
    summary: str | None = Field(None, description="Tóm tắt ngắn công việc/thành tựu chính.")


class Education(BaseModel):
    school: str | None = Field(None, description="Tên trường / cơ sở đào tạo.")
    degree: str | None = Field(None, description="Bằng cấp, vd 'Cử nhân', 'Thạc sĩ'.")
    field: str | None = Field(None, description="Chuyên ngành.")
    year: str | None = Field(None, description="Năm tốt nghiệp hoặc khoảng thời gian học.")


class Certificate(BaseModel):
    name: str = Field(description="Tên chứng chỉ, vd 'TOEIC', 'IELTS', 'AWS Certified Developer'.")
    detail: str | None = Field(None, description="Điểm/cấp độ nếu có, vd '945/990', '7.0', 'Associate'.")
    year: str | None = Field(None, description="Năm đạt được nếu có.")


class Language(BaseModel):
    name: str = Field(description="Tên ngôn ngữ, vd 'English', 'Japanese', 'Tiếng Nhật'.")
    proficiency: str | None = Field(
        None, description="Trình độ nếu có, vd 'Professional working', 'IELTS 7.0', 'bản ngữ'."
    )


class OtherItem(BaseModel):
    label: str = Field(description="Nhãn khối thông tin, vd 'Sở thích', 'Người tham chiếu', 'Hoạt động'.")
    content: str = Field(description="Nội dung của khối.")


class ParsedCV(BaseModel):
    """Thông tin ứng viên trích từ CV. Chỉ điền trường có dữ liệu thật; thiếu để None/[]."""

    full_name: str | None = Field(None, description="Họ tên đầy đủ của ứng viên.")
    email: str | None = Field(None, description="Email liên hệ.")
    phone: str | None = Field(None, description="Số điện thoại liên hệ.")
    skills: list[str] = Field(default_factory=list, description="Danh sách kỹ năng / công nghệ.")
    experiences: list[Experience] = Field(
        default_factory=list, description="Kinh nghiệm làm việc, mỗi mục một công ty/vị trí."
    )
    education: list[Education] = Field(
        default_factory=list, description="Học vấn, mỗi mục một bằng cấp/trường."
    )
    total_years_experience: float | None = Field(
        None, description="Tổng số năm kinh nghiệm (ước lượng từ CV), vd 3.5."
    )
    professional_summary: str | None = Field(
        None, description="Tóm tắt nghề nghiệp / mục tiêu ngắn gọn nếu CV có."
    )
    certificates: list[Certificate] = Field(
        default_factory=list, description="Chứng chỉ (TOEIC/IELTS/AWS...). Điểm/cấp độ để ở `detail`."
    )
    languages: list[Language] = Field(
        default_factory=list, description="Ngôn ngữ + trình độ (KHÁC với kỹ năng lập trình)."
    )
    awards: list[str] = Field(
        default_factory=list, description="Giải thưởng / thành tích nổi bật, mỗi mục một mô tả ngắn."
    )
    other: list[OtherItem] = Field(
        default_factory=list,
        description=(
            "LƯỚI AN TOÀN: CHỈ những khối CV KHÔNG thuộc trường nào ở trên (vd Sở thích, Người tham "
            "chiếu, Hoạt động ngoại khóa). TUYỆT ĐỐI không đặt chứng chỉ/ngôn ngữ/giải thưởng vào đây."
        ),
    )
