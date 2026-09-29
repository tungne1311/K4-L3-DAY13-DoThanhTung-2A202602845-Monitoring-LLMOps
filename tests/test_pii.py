from app.pii import scrub_text


def test_scrub_email() -> None:
    out = scrub_text("Email me at student@vinuni.edu.vn")
    assert "student@" not in out
    assert "REDACTED_EMAIL" in out


def test_scrub_common_vietnamese_phone_formats() -> None:
    phone_numbers = (
        "0901234567",
        "090 123 4567",
        "090.123.4567",
        "090-123-4567",
        "+84 90 123 4567",
    )

    for phone_number in phone_numbers:
        out = scrub_text(f"Contact: {phone_number}")
        assert phone_number not in out
        assert "REDACTED_PHONE_VN" in out


def test_scrub_cccd() -> None:
    out = scrub_text("CCCD của tôi là 001203004567")
    assert "001203004567" not in out
    assert "REDACTED_CCCD" in out


def test_scrub_credit_card_formats() -> None:
    for card in ("4111 1111 1111 1111", "4111-1111-1111-1111", "4111111111111111"):
        out = scrub_text(f"Card: {card}")
        assert card not in out
        assert "REDACTED_CREDIT_CARD" in out


def test_scrub_passport() -> None:
    out = scrub_text("Passport B1234567")
    assert "B1234567" not in out
    assert "REDACTED_PASSPORT" in out


def test_email_with_digits_is_fully_redacted() -> None:
    out = scrub_text("Mail 0987654321@gmail.com")
    assert "gmail.com" not in out
    assert "REDACTED_EMAIL" in out


def test_scrub_event_covers_nested_and_top_level_fields() -> None:
    from app.logging_config import scrub_event

    event = scrub_event(
        None,
        "info",
        {
            "event": "request_failed",
            "error_detail": "bad phone 0901234567",
            "payload": {"items": ["a@b.com"], "nested": {"card": "4111 1111 1111 1111"}},
            "latency_ms": 12,
        },
    )
    raw = str(event)
    assert "0901234567" not in raw
    assert "a@b.com" not in raw
    assert "4111 1111 1111 1111" not in raw
    assert event["latency_ms"] == 12
