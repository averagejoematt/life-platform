"""Tests for the new 5-section subscriber email template."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambdas'))

# Set required env vars before import
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("TABLE_NAME", "life-platform")


def test_build_subscriber_email_basic():
    """Test that _build_subscriber_email returns subject and valid HTML."""
    from chronicle_email_sender_lambda import _build_subscriber_email

    installment = {
        "title": "Test Week",
        "week_number": 5,
        "date": "2026-04-02",
        "content_html": "<p>First paragraph.</p><p>Second paragraph.</p><p>Third paragraph.</p>",
        "weekly_signal_data": '{"weight_lbs": 290, "avg_sleep_hours": 7.2, "training_sessions": 4, "habit_pct": 85, "avg_recovery_pct": 72, "avg_hrv_ms": 65, "journey_days": 5, "weight_delta_journey_lbs": 12, "featured_member_id": "lisa_park", "featured_observatory": {"slug": "sleep", "name": "Sleep Observatory", "hook": "How does recovery connect to sleep?"}}',
        "weekly_signal_wins_losses": '{"worked": [{"headline": "Protein target hit", "detail": "5 of 7 days above 180g"}], "didnt_work": [{"headline": "Late workout", "detail": "8pm session hurt sleep"}]}',
        "weekly_signal_board_quote": "Sleep architecture matters more than duration.",
    }
    subscriber = {"email": "test@example.com"}

    subject, html = _build_subscriber_email(installment, subscriber)

    assert "Week 5" in subject
    assert "Test Week" in subject
    assert "The Weekly Signal" in html
    assert "Week in Numbers" in html
    assert "290" in html  # weight
    assert "First paragraph" in html  # chronicle preview
    assert "Continue reading" in html
    assert "Protein target hit" in html  # worked
    assert "Late workout" in html  # didn't work
    assert "Sleep architecture" in html  # board quote
    assert "Lisa Park" in html  # board member
    assert "Sleep Observatory" in html  # observatory
    assert "Unsubscribe" in html  # CAN-SPAM


def test_build_subscriber_email_no_signal_data():
    """Test graceful fallback when signal data is missing."""
    from chronicle_email_sender_lambda import _build_subscriber_email

    installment = {
        "title": "Sparse Week",
        "week_number": 1,
        "date": "2026-04-01",
        "content_html": "<p>Just one paragraph.</p>",
    }
    subscriber = {"email": "test@example.com"}

    subject, html = _build_subscriber_email(installment, subscriber)

    assert "Sparse Week" in subject
    assert "Just one paragraph" in html
    assert "Unsubscribe" in html
    # Should not crash — sections are conditional


def test_extract_chronicle_preview():
    """Test chronicle preview extraction."""
    from chronicle_email_sender_lambda import _extract_chronicle_preview

    html = "<p>First.</p><p>Second.</p><p>Third.</p><p>Fourth.</p>"
    preview = _extract_chronicle_preview(html, max_paragraphs=2)
    assert "First." in preview
    assert "Second." in preview
    assert "Third." not in preview


def test_extract_chronicle_preview_empty():
    """Test preview with no paragraphs."""
    from chronicle_email_sender_lambda import _extract_chronicle_preview

    preview = _extract_chronicle_preview("")
    assert "available on the site" in preview


def test_bug_fix_subscriber_email_variable():
    """Verify the subscriber_email bug is fixed — should use subscriber.get('email')."""
    from chronicle_email_sender_lambda import _build_subscriber_email

    installment = {"title": "Bug Test", "week_number": 1, "content_html": "<p>Test</p>"}
    subscriber = {"email": "bugtest@example.com"}

    # This should NOT raise NameError for 'subscriber_email'
    subject, html = _build_subscriber_email(installment, subscriber)
    assert "bugtest%40example.com" in html  # unsubscribe URL contains URL-encoded email
