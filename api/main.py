"""
ContestTrade REST API (FastAPI)
提供异步分析任务的提交、状态查询、报告下载。
"""
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from fastapi import BackgroundTasks, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

app = FastAPI(
    title="ContestTrade API",
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

# CORS：内部使用可放宽，公网部署请限制域名
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 项目根目录（兼容本地和 Docker /app）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
JOBS_DIR = PROJECT_ROOT / "jobs"
JOBS_DIR.mkdir(exist_ok=True)


class AnalyzeRequest(BaseModel):
    market: str = Field(..., description="CN-Stock 或 US-Stock")
    trigger_time: str | None = Field(None, description="触发时间，留空则使用当前交易日")


def _update_status(job_id: str, **kwargs: Any) -> None:
    status_file = JOBS_DIR / job_id / "status.json"
    status: Dict[str, Any] = json.loads(status_file.read_text(encoding="utf-8"))
    status.update(kwargs)
    status_file.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_job_sync(job_id: str) -> None:
    """在子进程里跑分析，隔离不同市场的环境变量。"""
    job_dir = JOBS_DIR / job_id
    log_file = job_dir / "job.log"

    _update_status(job_id, status="running", stage="starting")

    env = os.environ.copy()
    # 子进程会读取 request.json 里的 market，这里保持原样即可

    cmd = [
        sys.executable,
        "-m",
        "api.run_analysis",
        str(job_dir),
    ]

    with open(log_file, "w", encoding="utf-8") as lf:
        proc = subprocess.Popen(
            cmd,
            stdout=lf,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(PROJECT_ROOT),
            env=env,
        )
        proc.wait()

    if proc.returncode == 0:
        _update_status(job_id, status="completed", stage="done")
    else:
        _update_status(job_id, status="failed", stage="error", error=f"exit code {proc.returncode}, see job.log")


@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest, background_tasks: BackgroundTasks):
    """提交分析任务，返回 job_id。本实例仅服务 A 股（CN-Stock）。"""
    if req.market != "CN-Stock":
        return JSONResponse(
            status_code=400,
            content={"error": "本实例仅支持 A 股（CN-Stock），请使用单独的 US-Stock 实例"},
        )
    job_id = str(uuid.uuid4())
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    # 保存请求（仅保留 market，强制即时触发，不支持历史回测）
    (job_dir / "request.json").write_text(
        json.dumps({"market": req.market}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 初始化状态
    (job_dir / "status.json").write_text(
        json.dumps({
            "job_id": job_id,
            "status": "pending",
            "stage": "pending",
            "market": req.market,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    background_tasks.add_task(_run_job_sync, job_id)
    return {"job_id": job_id, "status": "pending"}


@app.get("/api/jobs")
def list_jobs():
    """列出最近的任务（按创建时间倒序）"""
    jobs = []
    for job_dir in sorted(JOBS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:50]:
        status_file = job_dir / "status.json"
        if status_file.exists():
            data = json.loads(status_file.read_text(encoding="utf-8"))
            data.pop("_raw_result", None)
            if not data.get("created_at"):
                data["created_at"] = datetime.fromtimestamp(
                    status_file.stat().st_mtime
                ).strftime("%Y-%m-%d %H:%M:%S")
            jobs.append(data)
    return {"jobs": jobs}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    """查询任务状态"""
    status_file = JOBS_DIR / job_id / "status.json"
    if not status_file.exists():
        return JSONResponse(status_code=404, content={"error": "job not found"})
    return json.loads(status_file.read_text(encoding="utf-8"))


@app.get("/api/jobs/{job_id}/log")
def get_job_log(job_id: str):
    """查询任务日志"""
    log_file = JOBS_DIR / job_id / "job.log"
    if not log_file.exists():
        return JSONResponse(status_code=404, content={"error": "log not found"})
    return {"log": log_file.read_text(encoding="utf-8")}


@app.get("/api/jobs/{job_id}/report", response_class=HTMLResponse)
def get_job_report(job_id: str):
    """获取 HTML 报告"""
    report_paths = [
        JOBS_DIR / job_id / "report.html",
        PROJECT_ROOT / "report_deck.html",
    ]
    for path in report_paths:
        if path.exists():
            return HTMLResponse(content=path.read_text(encoding="utf-8"))
    return JSONResponse(status_code=404, content={"error": "report not found"})


@app.get("/api/jobs/{job_id}/result")
def get_job_result(job_id: str):
    """获取原始结果（JSON 摘要）"""
    result_file = JOBS_DIR / job_id / "result_summary.json"
    if not result_file.exists():
        return JSONResponse(status_code=404, content={"error": "result not found"})
    return json.loads(result_file.read_text(encoding="utf-8"))


@app.get("/api/health")
def health():
    return {"status": "ok", "jobs_dir": str(JOBS_DIR)}
