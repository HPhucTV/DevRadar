"""Unit tests for HTML-to-structured-markdown extraction and noise pruning."""

from __future__ import annotations

from time import perf_counter

import pytest

from devradar.ingestion.adapters.html_text import html_to_text, redact_contacts
from devradar.source_recipes.parser import _clean_multiline


def test_html_to_text_structured_sections() -> None:
    html = """
    <div class="job-detail">
        <h3>Mô tả công việc</h3>
        <p>Tham gia phát triển các tính năng backend cho hệ thống DevRadar.</p>
        <p>Chi tiết nhiệm vụ:</p>
        <ul>
            <li>Thiết kế database schema PostgreSQL và tối ưu query.</li>
            <li>Xây dựng REST API bằng FastAPI.</li>
        </ul>
        <h3>Yêu cầu ứng viên</h3>
        <p>Kỹ năng bắt buộc:</p>
        <ul>
            <li>Có ít nhất 2 năm kinh nghiệm làm việc với Python.</li>
            <li>Thành thạo Docker và Docker Compose.</li>
        </ul>
        <h4>Quyền lợi được hưởng</h4>
        <ul>
            <li>Mức lương cạnh tranh từ 25.000.000 - 35.000.000 VNĐ.</li>
            <li>Review lương 2 lần/năm.</li>
        </ul>
    </div>
    """
    result = html_to_text(html)
    assert result == (
        "### Mô tả công việc\n\n"
        "Tham gia phát triển các tính năng backend cho hệ thống DevRadar.\n\n"
        "Chi tiết nhiệm vụ:\n\n"
        "- Thiết kế database schema PostgreSQL và tối ưu query.\n"
        "- Xây dựng REST API bằng FastAPI.\n\n"
        "### Yêu cầu ứng viên\n\n"
        "Kỹ năng bắt buộc:\n\n"
        "- Có ít nhất 2 năm kinh nghiệm làm việc với Python.\n"
        "- Thành thạo Docker và Docker Compose.\n\n"
        "### Quyền lợi được hưởng\n\n"
        "- Mức lương cạnh tranh từ 25.000.000 - 35.000.000 VNĐ.\n"
        "- Review lương 2 lần/năm."
    )


def test_html_to_text_strips_noise_containers() -> None:
    html = """
    <div class="main-content">
        <div class="job-description">
            <h3>Mô tả công việc</h3>
            <p>Phát triển phần mềm ứng dụng.</p>
            <ul>
                <li>Phân tích yêu cầu và viết code.</li>
            </ul>
        </div>
        <div class="box-suggest-job">
            <img src="suggested-job.png" alt="Suggested job">
            <h3>Việc làm gợi ý cho bạn</h3>
            <p>Tuyển Senior Node.js Developer - Lương 40M</p>
        </div>
        <div class="similar-jobs">
            <p>Tuyển Java Spring Boot Engineer</p>
        </div>
        <aside class="box-company">
            <h3>Giới thiệu công ty TechCorp</h3>
            <p>Công ty phần mềm hàng đầu với 1000 kỹ sư.</p>
        </aside>
        <div class="box-apply">
            <button>Ứng tuyển ngay</button>
            <button>Lưu tin tuyển dụng</button>
        </div>
        <div class="ads">
            <p>Quảng cáo khoá học AI</p>
        </div>
        <h3>Yêu cầu ứng viên</h3>
        <p>Nội dung hợp lệ sau các khung nhiễu.</p>
    </div>
    """
    result = html_to_text(html)
    assert result is not None
    assert "### Mô tả công việc" in result
    assert "- Phân tích yêu cầu và viết code." in result

    # Noise must be completely stripped
    assert "Việc làm gợi ý" not in result
    assert "Senior Node.js" not in result
    assert "Java Spring Boot" not in result
    assert "TechCorp" not in result
    assert "1000 kỹ sư" not in result
    assert "Ứng tuyển ngay" not in result
    assert "Quảng cáo" not in result
    assert "### Yêu cầu ứng viên" in result
    assert "Nội dung hợp lệ sau các khung nhiễu." in result


def test_html_to_text_strips_topcv_noise_containers() -> None:
    html = """
    <div class="box-job-detail">
        <div class="job-description">
            <h3>Mô tả công việc</h3>
            <p>Lập trình phần mềm Python.</p>
        </div>
        <div class="job-related-version-2">
            <h3>Việc làm liên quan</h3>
            <p>Java Developer - Lương 50M</p>
        </div>
        <div class="box-general-group">
            <h3>Thông tin chung</h3>
            <p>Cấp bậc: Thực tập sinh</p>
        </div>
        <div class="box-feedback">
            <h3>Bạn thấy độ tin cậy thế nào?</h3>
            <p>Rất đáng tin cậy</p>
        </div>
        <div class="box-safe-job">
            <h3>Bí kíp tìm việc an toàn</h3>
            <p>Cảnh báo lừa đảo tuyển dụng</p>
        </div>
        <div class="job-detail__sidebar">
            <p>Sidebar content</p>
        </div>
    </div>
    """
    result = html_to_text(html)
    assert result == "### Mô tả công việc\n\nLập trình phần mềm Python."


def test_html_to_text_void_elements_do_not_extend_blocked_subtree() -> None:
    assert (
        html_to_text('<form><input name="secret"></form><h3>Yêu cầu</h3><p>Python</p>')
        == "### Yêu cầu\n\nPython"
    )


def test_html_to_text_redact_contacts() -> None:
    html = """
    <div>
        <h3>Liên hệ ứng tuyển</h3>
        <p>Gửi CV qua email: hr@company.com hoặc liên hệ hotline: 0912345678.</p>
    </div>
    """
    cleaned = html_to_text(html)
    assert cleaned is not None
    redacted, had_contacts = redact_contacts(cleaned)
    assert had_contacts is True
    assert "[redacted-email]" in redacted
    assert "[redacted-phone]" in redacted
    assert "hr@company.com" not in redacted
    assert "0912345678" not in redacted
    assert redacted.startswith("### Liên hệ ứng tuyển\n\n")


def test_clean_multiline() -> None:
    raw_html = "<h3>Yêu cầu</h3><ul><li>Python</li><li>FastAPI</li></ul>"
    from_html = _clean_multiline(raw_html)
    assert from_html == "### Yêu cầu\n\n- Python\n- FastAPI"

    multiline_text = "Dòng 1: Mô tả\n\n- Gạch đầu dòng 1\n- Gạch đầu dòng 2"
    from_text = _clean_multiline(multiline_text)
    assert from_text == "Dòng 1: Mô tả\n\n- Gạch đầu dòng 1\n- Gạch đầu dòng 2"


@pytest.mark.parametrize(
    "raw_html",
    [
        "<script>secret-token</script>",
        '<form><input value="private"></form>',
        '<div class="box-company"><img src="logo.png">Private company noise</div>',
    ],
)
def test_clean_multiline_never_falls_back_to_filtered_html(raw_html: str) -> None:
    assert _clean_multiline(raw_html) is None


def test_clean_multiline_preserves_generic_type_syntax_as_plain_text() -> None:
    raw = "Use List<T>, Promise<T>, and Map<K,V> daily"

    assert _clean_multiline(raw) == raw


@pytest.mark.parametrize(
    ("raw_html", "expected"),
    [
        ("<code>Python</code>", "Python"),
        ('<time datetime="2026-08-28">Today</time>', "Today"),
        ('<video><source src="intro.mp4"></video>', None),
        ("<job-card>Private role</job-card>", "Private role"),
        ("<job-card><script>secret-token</script></job-card>", None),
    ],
)
def test_clean_multiline_detects_standard_and_balanced_custom_html(
    raw_html: str,
    expected: str | None,
) -> None:
    assert _clean_multiline(raw_html) == expected


def test_clean_multiline_handles_many_unclosed_custom_tags_in_bounded_time() -> None:
    raw = "<job-note>" * 8_000
    started_at = perf_counter()

    assert _clean_multiline(raw) == raw
    assert perf_counter() - started_at < 2.0
