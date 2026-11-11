from __future__ import annotations

import hashlib
import json
import re

import pytest
from _tools_fakes import FakeSource, frame, hand

from handcontrol.contracts import CameraState, Handedness, Quality
from handcontrol.tools import profile_compare as pc
from handcontrol.tools import report as rp
from handcontrol.tools.common import LiveSource, ToolError


def sample_report(**kw):
    base = dict(
        tool="demo", title="Deneme raporu", stem="hw_demo_20261112-101500",
        environment=rp.collect_environment({"gercek_cozunurluk": "640x480", "kamera_fps": 30.0}),
        software={"paketler": {"mediapipe": "1.2.2"}, "model": {"manifest_sha256": "ab" * 32, "file_sha256": "ab" * 32, "eslesiyor": True}},
        conditions={"Işık": "tavan lambası", "Arka plan": "düz duvar", "Mesafe": "60 cm"},
        experiment=["20 alkış"], result_lines=["18/20 | tamam"], decision=rp.KARAR_GECTI, decision_note="tamam",
    )
    base.update(kw)
    return rp.Report(**base)


def test_markdown_has_all_template_rows():
    md = rp.render_markdown(sample_report())
    for row in ("Ortam", "Yazılım", "Koşul", "Deney", "Sonuç", "Karar"):
        assert re.search(rf"^\| {row} \|", md, re.M), row
    assert "tavan lambası" in md and "**geçti**" in md and "640x480" in md
    assert "eşleşiyor" in md
    assert "18/20 \\| tamam" in md            # pipes escaped inside table cells


def test_karar_vocabulary_enforced():
    with pytest.raises(ValueError):
        sample_report(decision="belki")
    assert set(rp.KARARLAR) == {"geçti", "kaldı", "yapılmadı"}


def test_save_report_names_and_content(tmp_path):
    rep = sample_report(raw={"sayim": 3})
    md, js = rp.save_report(rep, tmp_path / "Docs" / "reports")
    assert md.name == "hw_demo_20261112-101500.md" and js.name == "hw_demo_20261112-101500.json"
    data = json.loads(js.read_text(encoding="utf-8"))
    assert data["raw"] == {"sayim": 3} and data["decision"] == "geçti"
    assert re.fullmatch(r"hw_finger_test_\d{8}-\d{6}", rp.timestamp_stem("finger_test"))


def test_environment_and_software_filled_automatically():
    env = rp.collect_environment({"kamera_fps": 30})
    assert env["cpu"] and env["windows"] and env["kamera"] == {"kamera_fps": 30}
    sw = rp.collect_software()
    assert "mediapipe" in sw["paketler"] and "python" in sw["paketler"]
    assert "manifest_sha256" in sw["model"]


def test_model_sha_from_manifest_and_file(tmp_path):
    (tmp_path / "assets" / "models").mkdir(parents=True)
    blob = b"model-bytes"
    (tmp_path / "assets" / "models" / "hand_landmarker.task").write_bytes(blob)
    sha = hashlib.sha256(blob).hexdigest()
    (tmp_path / "assets" / "model_manifest.json").write_text(
        json.dumps({"models": [{"sha256": sha, "local_path": "assets/models/hand_landmarker.task"}]}), encoding="utf-8")
    info = rp.model_info(tmp_path)
    assert info["manifest_sha256"] == sha and info["file_sha256"] == sha and info["eslesiyor"] is True
    (tmp_path / "assets" / "models" / "hand_landmarker.task").write_bytes(b"changed")
    assert rp.model_info(tmp_path)["eslesiyor"] is False


def test_report_json_has_no_frames_or_landmarks():
    js = json.dumps(rp.report_to_json(sample_report()))
    assert "landmarks" not in js and "frames" not in js


# ---------------------------------------------------------------- live source camera errors


class FakeCamera:
    def __init__(self, state, error=None):
        self.state, self.last_error = state, error
        self.stopped = 0
        self.actual_width = self.actual_height = 0
        self.actual_fps = 0.0

    def start(self):
        pass

    def wait_for_state(self, states, timeout=5.0):
        return True

    def stop(self):
        self.stopped += 1

    def read_latest(self, timeout=0.0):
        return None


class FakeTracker:
    def load(self):
        pass

    def close(self):
        pass


def test_live_source_prints_camera_turkish_message_and_releases():
    from handcontrol.camera import MSG_BUSY

    cam = FakeCamera(CameraState.ERROR, MSG_BUSY)
    src = LiveSource(camera=cam, tracker=FakeTracker(), extractor=object())
    with pytest.raises(ToolError) as e:
        src.open()
    assert str(e.value) == MSG_BUSY and cam.stopped == 1


def test_live_source_mid_run_camera_error_raises():
    cam = FakeCamera(CameraState.RUNNING)
    src = LiveSource(camera=cam, tracker=FakeTracker(), extractor=object())
    src.open()
    cam.state, cam.last_error = CameraState.ERROR, "Kamera bağlantısı koptu."
    with pytest.raises(ToolError, match="koptu"):
        src.next()


# ---------------------------------------------------------------- profile_compare


def test_profile_compare_side_by_side(console, out_dir):
    def factory(w, h):
        def prov(t):
            return frame(t, hand(Handedness.RIGHT)) if w == 640 else frame(t, hand(Handedness.RIGHT, quality=Quality.DEGRADED))
        return FakeSource(prov, info={"kamera_fps": 30.0 if w == 640 else 24.0})

    run = pc.ProfileRun(factory, console, seconds_per_pose=1.0, out_dir=out_dir, software={})
    report = run.execute()
    assert [r["istenen"] for r in run.rows] == ["640x480", "1280x720"]
    assert report.status == rp.STATUS_TAMAM
    md = run.md_path.read_text(encoding="utf-8")
    assert "Yan yana karşılaştırma" in md and "640x480" in md and "1280x720" in md
    # SAĞ-only poses have expected=1 hand -> 640 profile usable; DEGRADED profile not
    assert run.rows[0]["kullanilabilir_kapsama_yuzde"] > run.rows[1]["kullanilabilir_kapsama_yuzde"] == 0.0


def test_profile_compare_ctrl_c_partial(console, out_dir):
    made = []

    def factory(w, h):
        s = FakeSource(lambda t: frame(t, hand()), interrupt_after=(10_000 if w == 640 else 5))
        made.append(s)
        return s

    run = pc.ProfileRun(factory, console, seconds_per_pose=1.0, out_dir=out_dir, software={})
    report = run.execute()
    assert report.status == rp.STATUS_YARIM and len(run.rows) == 1
    assert all(s.closed >= 1 for s in made)
