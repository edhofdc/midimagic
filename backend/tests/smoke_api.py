#!/usr/bin/env python3
"""End-to-end smoke test for the MidiMagic API (no external deps)."""
import json
import mimetypes
import sys
import time
import urllib.request
import uuid
from pathlib import Path

BASE = "http://127.0.0.1:8892"


def post_multipart(path: str, file_path: Path, fields: dict) -> dict:
    boundary = uuid.uuid4().hex
    body = b""
    for k, v in fields.items():
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode()
        body += f"{v}\r\n".encode()
    ctype = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    body += f"--{boundary}\r\n".encode()
    body += (
        f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
        f"Content-Type: {ctype}\r\n\r\n"
    ).encode()
    body += file_path.read_bytes()
    body += f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        BASE + path, data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read())


def get_json(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=120) as r:
        return json.loads(r.read())


def get_bytes(path: str) -> bytes:
    with urllib.request.urlopen(BASE + path, timeout=120) as r:
        return r.read()


def main() -> int:
    wav = Path(sys.argv[1] if len(sys.argv) > 1 else "data/test/melody_stereo.wav")
    stems = "--stems" in sys.argv

    print("health:", json.dumps(get_json("/api/health")["engines"], indent=2))

    fields = {"min_note_length": "0.05"}
    if stems:
        fields.update({"stems": "true", "stem_mode": "vocals", "target": "melody"})

    t0 = time.time()
    created = post_multipart("/api/jobs", wav, fields)
    jid = created["job_id"]
    print(f"\njob created: {jid}  (stems={stems})")

    last = ""
    while time.time() - t0 < 3000:
        time.sleep(2)
        st = get_json(f"/api/jobs/{jid}")
        line = f"  {st['status']:8} {st['stage']:12} {st['progress']*100:5.1f}%  notes={st['note_count']}"
        if line != last:
            print(line)
            last = line
        if st["status"] in ("done", "error"):
            break

    st = get_json(f"/api/jobs/{jid}")
    if st["status"] != "done":
        print("FAILED:", st.get("error"))
        for e in st.get("events", [])[-6:]:
            print("   ", e["stage"], e["message"][:160])
        return 1

    print(f"\nOK in {time.time()-t0:.1f}s  notes={st['note_count']} duration={st['duration']:.1f}s")
    print("stems:", list(st.get("stems", {}).keys()))

    midi = get_bytes(f"/api/jobs/{jid}/midi")
    print("midi bytes:", len(midi), "header:", midi[:4])
    assert midi[:4] == b"MThd", "MIDI header missing"

    audio = get_bytes(f"/api/jobs/{jid}/audio")[:4]
    print("audio preview header:", audio)

    # range request
    req = urllib.request.Request(
        BASE + f"/api/jobs/{jid}/audio", headers={"Range": "bytes=0-99"}
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        print("range status:", r.status, "len:", len(r.read()))

    # share
    req = urllib.request.Request(
        BASE + "/api/shares",
        data=json.dumps({"job_id": jid}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        share = json.loads(r.read())
    print("share:", share["url"], "->", share["slug"])
    print("share meta:", get_json(f"/api/shares/{share['slug']}"))
    print("share midi bytes:", len(get_bytes(f"/api/shares/{share['slug']}/midi")))

    # transformed export
    shifted = get_bytes(f"/api/jobs/{jid}/midi?semitones=2&tempo=1.25")
    print("transposed export bytes:", len(shifted), shifted[:4])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
