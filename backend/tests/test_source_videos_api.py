from flow_helpers import create_uploaded_source_video, run_job_pipeline_smoke


async def test_approved_import_requires_import_id(client, actor_headers) -> None:
    brand_response = await client.post(
        "/api/v1/brand-profiles",
        headers=actor_headers,
        json={
            "name": "Import Brand",
            "language": "en",
            "caption_style_defaults": {},
            "overlay_policy": {},
            "music_policy": {},
            "platform_defaults": {},
        },
    )
    assert brand_response.status_code == 200

    response = await client.post(
        "/api/v1/source-videos",
        headers=actor_headers,
        json={
            "brand_profile_id": brand_response.json()["id"],
            "rights_attestation": True,
            "source_type": "approved_import",
            "provenance": {
                "provenance_type": "approved_import",
                "provider": "manual",
                "source_uri": "https://example.com/video",
            },
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_get_source_video_returns_artifacts_by_role_after_ingest(
    client,
    actor_headers,
    session_factory,
    storage_root,
    monkeypatch,
) -> None:
    context = await run_job_pipeline_smoke(
        client=client,
        actor_headers=actor_headers,
        session_factory=session_factory,
        storage_root=storage_root,
        monkeypatch=monkeypatch,
    )

    response = await client.get(f"/api/v1/source-videos/{context['source_video_id']}", headers=actor_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["canonical_asset_id"] == payload["artifacts"]["source_asset"]["artifact_id"]
    assert payload["artifacts"]["canonical_video"]["artifact_id"] == payload["artifacts"]["proxy_video"]["artifact_id"]
    assert payload["artifacts"]["canonical_video"]["artifact_id"] != payload["canonical_asset_id"]
    assert payload["artifacts"]["normalized_audio"]["role"] == "normalized_audio"
    assert payload["artifacts"]["thumbnails"]["role"] == "thumbnails"
    assert payload["provenance"] == []


async def test_get_source_video_returns_provenance_for_approved_import(client, actor_headers) -> None:
    brand_response = await client.post(
        "/api/v1/brand-profiles",
        headers=actor_headers,
        json={
            "name": "Approved Import Brand",
            "language": "en",
            "caption_style_defaults": {},
            "overlay_policy": {},
            "music_policy": {},
            "platform_defaults": {},
        },
    )
    assert brand_response.status_code == 200

    create_response = await client.post(
        "/api/v1/source-videos",
        headers=actor_headers,
        json={
            "approved_import_id": "approved-import-123",
            "brand_profile_id": brand_response.json()["id"],
            "rights_attestation": True,
            "source_type": "approved_import",
            "duration_ms": 45_000,
            "provenance": {
                "provenance_type": "approved_import",
                "provider": "manual-review",
                "source_uri": "https://example.com/video/approved-import-123",
                "approved_by": "moderator-1",
            },
        },
    )
    assert create_response.status_code == 200

    detail_response = await client.get(f"/api/v1/source-videos/{create_response.json()['id']}", headers=actor_headers)

    assert detail_response.status_code == 200
    payload = detail_response.json()
    assert payload["artifacts"]["source_asset"]["role"] == "source_asset"
    assert payload["artifacts"]["source_asset"]["kind"] == "source_video"
    assert len(payload["provenance"]) == 1
    assert payload["provenance"][0]["provenance_type"] == "approved_import"
    assert payload["provenance"][0]["provider"] == "manual-review"
    assert payload["provenance"][0]["approved_by"] == "moderator-1"
