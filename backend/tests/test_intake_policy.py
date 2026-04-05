from app.services.intake_policy import IntakeInput, evaluate_intake


def test_intake_accepts_in_scope_uploaded_asset() -> None:
    decision = evaluate_intake(
        IntakeInput(
            rights_attestation=True,
            duration_ms=30 * 60 * 1000,
            language="en",
            deployment_language="en",
            source_type="uploaded_asset",
            has_provenance=True,
            speaker_count_estimate=1,
        )
    )
    assert decision.outcome == "accepted"
    assert "audio_quality_unchecked" in decision.warnings


def test_intake_requires_manual_review_for_language_mismatch() -> None:
    decision = evaluate_intake(
        IntakeInput(
            rights_attestation=True,
            duration_ms=30 * 60 * 1000,
            language="ru",
            deployment_language="en",
            source_type="uploaded_asset",
            has_provenance=True,
            speaker_count_estimate=1,
        )
    )
    assert decision.outcome == "manual_review_required"
    assert decision.reason_codes == ["language_mismatch"]


def test_intake_rejects_missing_rights() -> None:
    decision = evaluate_intake(
        IntakeInput(
            rights_attestation=False,
            duration_ms=30 * 60 * 1000,
            language="en",
            deployment_language="en",
            source_type="uploaded_asset",
            has_provenance=True,
            speaker_count_estimate=1,
        )
    )
    assert decision.outcome == "rejected_out_of_scope"
    assert decision.reason_codes == ["rights_missing"]
