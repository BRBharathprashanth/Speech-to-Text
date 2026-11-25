"""Fast CRUD, search, pagination, and stats endpoint tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_full_crud_and_stats_flow(client: TestClient) -> None:
    # Create 3 records (English, Hindi, Mixed)
    r_en = client.post(
        "/api/transcriptions",
        json={"transcription_text": "FastAPI and PostgreSQL integration.", "detected_language": "en"},
    )
    assert r_en.status_code == 201
    en_id = r_en.json()["id"]
    assert r_en.json()["script_mix"] == "english"

    r_hi = client.post(
        "/api/transcriptions",
        json={"transcription_text": "आज मुझे एक नया प्रोजेक्ट बनाना है।", "detected_language": "hi"},
    )
    assert r_hi.status_code == 201
    assert r_hi.json()["script_mix"] == "hindi"

    r_mix = client.post(
        "/api/transcriptions",
        json={"transcription_text": "आज मुझे FastAPI backend complete करना है।", "detected_language": "hi"},
    )
    assert r_mix.status_code == 201
    assert r_mix.json()["script_mix"] == "mixed"

    # Stats reflect exact DB counts
    stats_res = client.get("/api/stats")
    assert stats_res.status_code == 200
    assert stats_res.json() == {
        "total": 3,
        "hindi": 1,
        "english": 1,
        "mixed": 1,
        "other": 0,
    }

    # Search and filter
    search_res = client.get("/api/transcriptions", params={"q": "PostgreSQL"})
    assert search_res.status_code == 200
    assert search_res.json()["total"] == 1
    assert search_res.json()["items"][0]["id"] == en_id

    mix_res = client.get("/api/transcriptions", params={"script_mix": "mixed"})
    assert mix_res.status_code == 200
    assert mix_res.json()["total"] == 1

    # Pagination
    page1 = client.get("/api/transcriptions", params={"page": 1, "page_size": 2})
    assert page1.status_code == 200
    assert len(page1.json()["items"]) == 2
    assert page1.json()["total_pages"] == 2

    # Read single
    get_res = client.get(f"/api/transcriptions/{en_id}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == en_id

    # Update
    upd_res = client.put(
        f"/api/transcriptions/{en_id}",
        json={"transcription_text": "अब मुझे API integrate करनी है।"},
    )
    assert upd_res.status_code == 200
    assert upd_res.json()["script_mix"] == "mixed"

    # Delete
    del_res = client.delete(f"/api/transcriptions/{en_id}")
    assert del_res.status_code == 200
    assert del_res.json()["deleted"] is True

    # Confirm 404 after delete
    assert client.get(f"/api/transcriptions/{en_id}").status_code == 404
    assert client.delete(f"/api/transcriptions/{en_id}").status_code == 404
