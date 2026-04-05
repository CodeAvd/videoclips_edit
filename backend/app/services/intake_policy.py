from dataclasses import dataclass, field


@dataclass(slots=True)
class IntakeInput:
    rights_attestation: bool
    duration_ms: int | None
    language: str | None
    deployment_language: str
    source_type: str
    has_provenance: bool
    speaker_count_estimate: int | None


@dataclass(slots=True)
class IntakeDecision:
    outcome: str
    reason_codes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


MIN_DURATION_MS = 20 * 60 * 1000
MAX_DURATION_MS = 120 * 60 * 1000
MAX_RECOMMENDED_SPEAKERS = 2


def evaluate_intake(input_data: IntakeInput) -> IntakeDecision:
    reason_codes: list[str] = []
    warnings: list[str] = []

    if not input_data.rights_attestation:
        return IntakeDecision(outcome="rejected_out_of_scope", reason_codes=["rights_missing"])

    if input_data.source_type == "approved_import" and not input_data.has_provenance:
        return IntakeDecision(outcome="rejected_out_of_scope", reason_codes=["provenance_missing"])

    if input_data.duration_ms is None:
        return IntakeDecision(outcome="manual_review_required", reason_codes=["duration_unknown"])
    if input_data.duration_ms < MIN_DURATION_MS or input_data.duration_ms > MAX_DURATION_MS:
        return IntakeDecision(outcome="rejected_out_of_scope", reason_codes=["duration_unsupported"])

    if input_data.language is None:
        return IntakeDecision(outcome="manual_review_required", reason_codes=["language_unknown"])
    if input_data.language != input_data.deployment_language:
        return IntakeDecision(outcome="manual_review_required", reason_codes=["language_mismatch"])

    if input_data.speaker_count_estimate and input_data.speaker_count_estimate > MAX_RECOMMENDED_SPEAKERS:
        return IntakeDecision(outcome="manual_review_required", reason_codes=["speaker_count_high"])

    warnings.append("audio_quality_unchecked")
    return IntakeDecision(outcome="accepted", reason_codes=reason_codes, warnings=warnings)
