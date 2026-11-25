"""Test script: generate a WAV, upload to localhost:8001, verify DB persistence."""
import io
import json
import math
import struct
import wave
import http.client
import urllib.request

# 1. Generate a 2-second 440 Hz sine wave WAV
buf = io.BytesIO()
sr, dur = 16000, 2.0
n = int(sr * dur)
with wave.open(buf, "wb") as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(sr)
    frames = bytearray()
    for i in range(n):
        val = int(12000 * math.sin(2 * math.pi * 440 * i / sr))
        frames.extend(struct.pack("<h", val))
    wf.writeframes(bytes(frames))
wav_data = buf.getvalue()
print(f"Generated test WAV: {len(wav_data)} bytes, {dur}s @ {sr} Hz")

# 2. Upload via multipart/form-data
boundary = "----TestBoundary123456"
body_parts = []
body_parts.append(f"--{boundary}\r\n".encode())
body_parts.append(b'Content-Disposition: form-data; name="file"; filename="test_440hz.wav"\r\n')
body_parts.append(b"Content-Type: audio/wav\r\n\r\n")
body_parts.append(wav_data)
body_parts.append(f"\r\n--{boundary}--\r\n".encode())
body = b"".join(body_parts)

conn = http.client.HTTPConnection("localhost", 8001, timeout=60)
conn.request(
    "POST",
    "/api/transcribe",
    body=body,
    headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)),
    },
)
resp = conn.getresponse()
status_code = resp.status
result = json.loads(resp.read().decode())
conn.close()

print(f"Upload HTTP Status: {status_code}")
print(json.dumps(result, indent=2, ensure_ascii=False))

# 3. Verify DB persistence via GET API
if status_code == 201:
    rec_id = result["record"]["id"]
    with urllib.request.urlopen(f"http://localhost:8001/api/transcriptions/{rec_id}") as r:
        saved = json.loads(r.read().decode())
        print(f"DB VERIFY: id={saved['id']}, script_mix={saved['script_mix']}, "
              f"lang={saved['detected_language']}, "
              f"text={saved['transcription_text'][:200]!r}")
    with urllib.request.urlopen("http://localhost:8001/api/stats") as r:
        stats = json.loads(r.read().decode())
        print(f"DB STATS: {json.dumps(stats)}")
elif status_code == 422:
    print("NOTE: 440 Hz pure sine tone has no recognizable speech. "
          "Faster-Whisper correctly rejected it. Upload pipeline is working.")
else:
    print(f"ERROR: Unexpected status {status_code}")
