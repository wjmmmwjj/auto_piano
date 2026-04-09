from __future__ import annotations

import argparse
import importlib.util
import json
import mimetypes
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from playback.esp32_serial import probe_serial_ports, select_best_esp32_probe
from playback.project_score_tools import normalize_score, score_to_esp32_lines

APPS_DIR = BASE_DIR / "apps"
UI_DIR = APPS_DIR / "dashboard_ui"
SONGS_DIR = BASE_DIR / "songs"
PLAYBACK_DIR = BASE_DIR / "playback"
BUTTON_DIR = BASE_DIR / "button"
VENV_PYTHON = BASE_DIR / ".venv311" / "Scripts" / "python.exe"
CREATE_NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_LOG_LINES = 1200
SERVER_STARTED_AT = time.time()


def configure_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", line_buffering=True)
        except Exception:
            pass


def choose_python() -> Path:
    if VENV_PYTHON.exists():
        return VENV_PYTHON
    return Path(sys.executable).resolve()


def project_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(BASE_DIR).as_posix()
    except Exception:
        return path.resolve().as_posix()


def list_song_entries() -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    if not SONGS_DIR.exists():
        return entries

    for path in sorted(SONGS_DIR.glob("*.py"), key=lambda item: item.stem.casefold()):
        stat = path.stat()
        entries.append(
            {
                "name": path.stem,
                "path": str(path.resolve()),
                "relative_path": project_relative(path),
                "modified_at": stat.st_mtime,
                "size_bytes": stat.st_size,
            }
        )
    return entries


def load_song_module(score_path: Path):
    module_name = f"dashboard_song_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, score_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"無法載入歌曲檔案：{score_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def estimate_commands_duration_sec(commands: list[str]) -> float:
    total_ms = 0
    for raw_line in commands:
        line = str(raw_line).strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) >= 2 and parts[0].upper() == "WAIT":
            try:
                total_ms += int(parts[1])
            except ValueError:
                continue
    return max(0.0, total_ms / 1000.0)


def estimate_song_duration_sec(score_path: Path) -> float:
    module = load_song_module(score_path)

    embedded_lines = getattr(module, "ESP32_LINES", None)
    if isinstance(embedded_lines, list) and embedded_lines:
        return estimate_commands_duration_sec([str(line).strip() for line in embedded_lines if str(line).strip()])

    score = getattr(module, "SCORE", None)
    if isinstance(score, list) and score:
        commands = score_to_esp32_lines(normalize_score(score))
        return estimate_commands_duration_sec(commands)

    return 0.0


def serialize_probe(probe) -> dict[str, object]:
    return {
        "port": probe.port,
        "description": probe.description,
        "mode": probe.mode,
        "banners": list(probe.banners),
        "likely_esp32": probe.likely_esp32,
        "error": probe.error,
    }


def inspect_ports() -> dict[str, object]:
    probes = probe_serial_ports()
    best_main = select_best_esp32_probe(probes, expected_mode="main")
    best_tuner = select_best_esp32_probe(probes, expected_mode="tuner")
    return {
        "probes": [serialize_probe(probe) for probe in probes],
        "best_main_port": best_main.port if best_main is not None else "",
        "best_tuner_port": best_tuner.port if best_tuner is not None else "",
    }


def runtime_payload() -> dict[str, object]:
    python_path = choose_python()
    return {
        "project_root": str(BASE_DIR),
        "python_path": str(python_path),
        "venv_ready": python_path == VENV_PYTHON and VENV_PYTHON.exists(),
        "songs_count": len(list_song_entries()),
        "server_started_at": SERVER_STARTED_AT,
    }


def normalize_song_path(raw_value: str) -> Path:
    value = (raw_value or "").strip()
    if not value:
        raise ValueError("請先選一首歌。")

    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = (BASE_DIR / candidate).resolve()
    else:
        candidate = candidate.resolve()

    if not candidate.exists():
        raise ValueError(f"找不到歌曲檔案：{candidate}")
    if candidate.suffix.lower() != ".py":
        raise ValueError("只能選擇 .py 樂譜檔。")
    return candidate


def resolve_playback_port(raw_value: str) -> str:
    value = (raw_value or "").strip().upper()
    if value:
        return value

    inspection = inspect_ports()
    best_main_port = str(inspection.get("best_main_port", "") or "").strip()
    if best_main_port:
        return best_main_port

    raise ValueError("找不到已燒錄播放韌體的 ESP32，請先連接控制器或手動選擇 COM 埠。")


@dataclass
class TaskRecord:
    task_id: str
    kind: str
    title: str
    command: list[str]
    cwd: str
    process: subprocess.Popen | None
    status: str = "running"
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    returncode: int | None = None
    detached: bool = False
    metadata: dict[str, object] = field(default_factory=dict)
    result: dict[str, object] | None = None
    logs: deque[str] = field(default_factory=lambda: deque(maxlen=MAX_LOG_LINES))
    summary_path: Path | None = None
    cleanup_paths: list[Path] = field(default_factory=list)

    @property
    def pid(self) -> int | None:
        if self.process is None:
            return None
        return self.process.pid


class TaskStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tasks: dict[str, TaskRecord] = {}

    def list(self) -> list[dict[str, object]]:
        with self._lock:
            tasks = sorted(self._tasks.values(), key=lambda item: item.started_at, reverse=True)
            return [self._serialize(task, include_logs=False) for task in tasks]

    def get(self, task_id: str) -> dict[str, object] | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            return self._serialize(task, include_logs=True)

    def running_tasks(self, kind: str) -> list[TaskRecord]:
        with self._lock:
            return [task for task in self._tasks.values() if task.kind == kind and task.status in {"running", "stopping"}]

    def start(
        self,
        *,
        kind: str,
        title: str,
        command: list[str],
        cwd: Path,
        metadata: dict[str, object] | None = None,
        detached: bool = False,
        creationflags: int = 0,
        summary_path: Path | None = None,
        cleanup_paths: list[Path] | None = None,
    ) -> dict[str, object]:
        task_id = uuid.uuid4().hex[:10]
        merged_env = os.environ.copy()
        merged_env.setdefault("PYTHONUTF8", "1")
        merged_env.setdefault("PYTHONIOENCODING", "utf-8")
        merged_env.setdefault("SSLKEYLOGFILE", "")

        popen_kwargs: dict[str, object] = {
            "cwd": str(cwd),
            "env": merged_env,
            "stdin": subprocess.DEVNULL,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
        }
        if detached:
            popen_kwargs["stdout"] = subprocess.DEVNULL
            popen_kwargs["stderr"] = subprocess.DEVNULL
        else:
            popen_kwargs["stdout"] = subprocess.PIPE
            popen_kwargs["stderr"] = subprocess.STDOUT
            popen_kwargs["bufsize"] = 1
        if creationflags:
            popen_kwargs["creationflags"] = creationflags

        process = subprocess.Popen(command, **popen_kwargs)
        task = TaskRecord(
            task_id=task_id,
            kind=kind,
            title=title,
            command=command,
            cwd=str(cwd),
            process=process,
            detached=detached,
            metadata=dict(metadata or {}),
            summary_path=summary_path,
            cleanup_paths=list(cleanup_paths or []),
        )
        task.logs.append("已啟動。")

        with self._lock:
            self._tasks[task_id] = task

        if process.stdout is not None:
            threading.Thread(target=self._pump_output, args=(task,), daemon=True).start()
        threading.Thread(target=self._watch, args=(task,), daemon=True).start()

        return self._serialize(task, include_logs=True)

    def stop(self, task_id: str) -> dict[str, object]:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError(task_id)
            if task.process is None or task.status not in {"running", "stopping"}:
                return self._serialize(task, include_logs=True)
            if task.status != "stopping":
                task.status = "stopping"
                task.logs.append("正在停止任務...")

        threading.Thread(target=self._terminate, args=(task,), daemon=True).start()
        return self._serialize(task, include_logs=True)

    def _pump_output(self, task: TaskRecord) -> None:
        if task.process is None or task.process.stdout is None:
            return
        try:
            for raw_line in task.process.stdout:
                line = raw_line.rstrip()
                if not line:
                    continue
                with self._lock:
                    task.logs.append(line)
        finally:
            try:
                task.process.stdout.close()
            except Exception:
                pass

    def _watch(self, task: TaskRecord) -> None:
        if task.process is None:
            return
        returncode = task.process.wait()

        result: dict[str, object] | None = None
        if task.summary_path is not None and task.summary_path.exists():
            try:
                result = json.loads(task.summary_path.read_text(encoding="utf-8"))
            except Exception as exc:
                with self._lock:
                    task.logs.append(f"無法讀取摘要 JSON：{exc}")

        with self._lock:
            task.returncode = returncode
            task.ended_at = time.time()
            if task.status == "stopping":
                task.status = "stopped"
            elif returncode == 0:
                task.status = "completed"
            else:
                task.status = "failed"
            if result is not None:
                task.result = result
            task.logs.append(f"任務結束（exit code {returncode}）。")

        for path in task.cleanup_paths:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass

    def _terminate(self, task: TaskRecord) -> None:
        process = task.process
        if process is None:
            return

        try:
            process.terminate()
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                with self._lock:
                    task.logs.append("停止逾時，改用強制結束。")
                process.kill()
            except Exception as exc:
                with self._lock:
                    task.logs.append(f"強制結束失敗：{exc}")
        except Exception as exc:
            with self._lock:
                task.logs.append(f"停止任務失敗：{exc}")

    def _serialize(self, task: TaskRecord, *, include_logs: bool) -> dict[str, object]:
        ended_at = task.ended_at
        now = time.time()
        return {
            "id": task.task_id,
            "kind": task.kind,
            "title": task.title,
            "status": task.status,
            "command": task.command,
            "command_text": subprocess.list2cmdline(task.command),
            "cwd": task.cwd,
            "started_at": task.started_at,
            "ended_at": ended_at,
            "duration_sec": (ended_at or now) - task.started_at,
            "returncode": task.returncode,
            "pid": task.pid,
            "detached": task.detached,
            "metadata": task.metadata,
            "result": task.result,
            "logs": list(task.logs) if include_logs else [],
            "log_tail": list(task.logs)[-24:],
        }


TASKS = TaskStore()


def ensure_single_running(kind: str, message: str) -> None:
    if TASKS.running_tasks(kind):
        raise ValueError(message)


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "AutoPianoDashboard/1.0"

    def log_message(self, format: str, *args) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/runtime":
            self._json_response(runtime_payload())
            return
        if path == "/api/songs":
            self._json_response({"songs": list_song_entries()})
            return
        if path == "/api/ports":
            self._json_response(inspect_ports())
            return
        if path == "/api/tasks":
            self._json_response({"tasks": TASKS.list()})
            return
        if path.startswith("/api/tasks/"):
            task_id = path.removeprefix("/api/tasks/").strip("/")
            if not task_id:
                self._error_response(HTTPStatus.NOT_FOUND, "找不到任務。")
                return
            task = TASKS.get(task_id)
            if task is None:
                self._error_response(HTTPStatus.NOT_FOUND, "找不到任務。")
                return
            self._json_response(task)
            return

        self._serve_static(path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        payload = self._read_json_body()

        try:
            if path == "/api/tasks/transcribe":
                response = self._start_transcription(payload)
            elif path == "/api/tasks/playback":
                response = self._start_playback(payload)
            elif path == "/api/tasks/safezero":
                response = self._start_safezero(payload)
            elif path == "/api/tasks/visualize":
                response = self._start_visualizer(payload)
            elif path == "/api/tasks/sound":
                response = self._start_sound_bridge(payload)
            elif path == "/api/tasks/tool":
                response = self._launch_tool()
            elif path.endswith("/stop") and path.startswith("/api/tasks/"):
                task_id = path.removeprefix("/api/tasks/").removesuffix("/stop").strip("/")
                response = TASKS.stop(task_id)
            else:
                self._error_response(HTTPStatus.NOT_FOUND, "找不到 API。")
                return
        except KeyError:
            self._error_response(HTTPStatus.NOT_FOUND, "找不到任務。")
            return
        except ValueError as exc:
            self._error_response(HTTPStatus.BAD_REQUEST, str(exc))
            return
        except Exception as exc:
            self._error_response(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
            return

        self._json_response(response, status=HTTPStatus.CREATED)

    def _start_transcription(self, payload: dict[str, object]) -> dict[str, object]:
        query = str(payload.get("query", "") or "").strip()
        mode = str(payload.get("mode", "full") or "full").strip().lower()
        force_cpu = bool(payload.get("force_cpu", False))
        if not query:
            raise ValueError("請輸入歌曲名稱或 YouTube 連結。")
        if mode not in {"auto", "quick", "full"}:
            raise ValueError("轉譜模式不正確。")

        fd, raw_summary_path = tempfile.mkstemp(prefix="auto-piano-dashboard-", suffix=".json")
        os.close(fd)
        summary_path = Path(raw_summary_path)

        command = [
            str(choose_python()),
            str(PLAYBACK_DIR / "song_workflow.py"),
            "--mode",
            mode,
            "--summary-json",
            str(summary_path),
        ]
        if force_cpu:
            command.append("--cpu")
        command.append(query)

        return TASKS.start(
            kind="transcribe",
            title=f"AI 轉譜：{query}",
            command=command,
            cwd=BASE_DIR,
            metadata={"query": query, "mode": mode, "force_cpu": force_cpu},
            summary_path=summary_path,
            cleanup_paths=[summary_path],
        )

    def _start_playback(self, payload: dict[str, object]) -> dict[str, object]:
        score_path = normalize_song_path(str(payload.get("song_path", "") or ""))
        overlap = int(payload.get("overlap", 3) or 3)
        if overlap < 1:
            overlap = 1
        com_port = resolve_playback_port(str(payload.get("com_port", "") or ""))
        total_duration_sec = estimate_song_duration_sec(score_path)

        command = [
            str(choose_python()),
            str(PLAYBACK_DIR / "play_score.py"),
            "--file",
            str(score_path),
            "--com",
            com_port,
            "--overlap",
            str(overlap),
        ]
        return TASKS.start(
            kind="playback",
            title=f"真實彈奏：{score_path.stem}",
            command=command,
            cwd=BASE_DIR,
            metadata={
                "song_path": str(score_path),
                "song_name": score_path.stem,
                "com_port": com_port,
                "overlap": overlap,
                "total_duration_sec": total_duration_sec,
            },
        )

    def _start_safezero(self, payload: dict[str, object]) -> dict[str, object]:
        ensure_single_running("playback", "正在播放或歸零中，請先停止目前的進度。")
        ensure_single_running("safezero", "指令已經在執行中。")
        com_port = resolve_playback_port(str(payload.get("com_port", "") or ""))

        command = [
            str(choose_python()),
            str(PLAYBACK_DIR / "play_score.py"),
            "--safezero",
        ]
        if com_port:
            command.extend(["--com", com_port])

        return TASKS.start(
            kind="safezero",
            title="全部按鍵歸零",
            command=command,
            cwd=BASE_DIR,
            metadata={
                "com_port": com_port,
            },
        )

    def _start_visualizer(self, payload: dict[str, object]) -> dict[str, object]:
        score_path = normalize_song_path(str(payload.get("song_path", "") or ""))
        total_duration_sec = estimate_song_duration_sec(score_path)
        command = [str(choose_python()), str(APPS_DIR / "visualize_score.py"), str(score_path)]
        return TASKS.start(
            kind="visualize",
            title=f"視覺化：{score_path.stem}",
            command=command,
            cwd=BASE_DIR,
            metadata={
                "song_path": str(score_path),
                "song_name": score_path.stem,
                "total_duration_sec": total_duration_sec,
            },
        )

    def _start_sound_bridge(self, payload: dict[str, object]) -> dict[str, object]:
        ensure_single_running("sound", "聲音橋接已經在執行，先停止目前的橋接再重開。")
        backend = str(payload.get("backend", "auto") or "auto").strip().lower()
        if backend not in {"auto", "speaker", "midi"}:
            raise ValueError("聲音輸出模式不正確。")

        command = [
            str(choose_python()),
            str(BUTTON_DIR / "midi_bridge.py"),
            "--backend",
            backend,
        ]
        return TASKS.start(
            kind="sound",
            title=f"聲音橋接：{backend}",
            command=command,
            cwd=BASE_DIR,
            metadata={"backend": backend},
        )

    def _launch_tool(self) -> dict[str, object]:
        command = [str(choose_python()), str(APPS_DIR / "piano_motor_tuner.py")]
        return TASKS.start(
            kind="tool",
            title="Motor Tool",
            command=command,
            cwd=BASE_DIR,
            detached=True,
            creationflags=CREATE_NEW_CONSOLE,
            metadata={"standalone": True, "reusable": True},
        )

    def _read_json_body(self) -> dict[str, object]:
        raw_length = self.headers.get("Content-Length", "0").strip()
        if not raw_length:
            return {}
        content_length = int(raw_length)
        if content_length <= 0:
            return {}
        raw_body = self.rfile.read(content_length)
        if not raw_body:
            return {}
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except Exception as exc:
            raise ValueError(f"JSON 格式錯誤：{exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("JSON 內容必須是物件。")
        return payload

    def _json_response(self, payload: dict[str, object], *, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error_response(self, status: HTTPStatus, message: str) -> None:
        self._json_response({"error": message}, status=status)

    def _serve_static(self, path: str) -> None:
        requested = path or "/"
        if requested == "/":
            requested = "/index.html"

        local_path = self._resolve_static_path(requested)
        if local_path is None or not local_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return

        content_type, _ = mimetypes.guess_type(str(local_path))
        data = local_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type or 'application/octet-stream'}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _resolve_static_path(self, raw_path: str) -> Path | None:
        cleaned = unquote(raw_path.lstrip("/"))
        candidate = (UI_DIR / cleaned).resolve()
        try:
            candidate.relative_to(UI_DIR.resolve())
        except Exception:
            return None
        return candidate


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Auto Piano 本機整合控制台。")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Dashboard 綁定的主機位址。")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Dashboard 綁定的埠號。")
    return parser


def main() -> int:
    configure_utf8_console()
    parser = build_parser()
    args = parser.parse_args()

    if not UI_DIR.exists():
        raise RuntimeError(f"找不到 Dashboard 前端檔案：{UI_DIR}")

    server = DashboardServer((args.host, args.port), DashboardHandler)
    host, port = server.server_address
    print("Auto Piano Dashboard 已啟動")
    print(f"網址：http://{host}:{port}")
    print("Tool 仍可獨立啟用，也能從頁面重複開新視窗。")
    print("按 Ctrl+C 可停止 Dashboard。")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard 已停止。")
    finally:
        server.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
