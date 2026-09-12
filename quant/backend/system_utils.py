import os
import shutil
import subprocess
import threading


def _env_int(key: str, default: int) -> int:
    try:
        value = int(os.getenv(key, "").strip())
    except Exception:
        return default
    return value if value > 0 else default


def _env_str(key: str, default: str) -> str:
    value = os.getenv(key, "").strip()
    return value if value else default


def get_optimal_worker_count(task_type: str = "cpu", max_limit: int = None) -> int:
    """
    根据 CPU 核心数和任务类型自动选择并发数。

    Args:
        task_type: "cpu" (CPU 密集型，如回测、策略计算) 或 "io" (IO 密集型，如网络下载、数据库读写)
        max_limit: 强制最大并发数限制

    Returns:
        int: 建议的并发数
    """
    cpu_count = os.cpu_count() or 1

    if task_type == "cpu":
        # CPU 密集型任务，并发数建议与物理核心数一致，避免过多的上下文切换
        # 对于 Python 而言，由于 GIL 存在，多进程推荐核心数
        count = cpu_count
    elif task_type == "io":
        # IO 密集型任务（如网络请求），可以显著高于核心数
        # 这里默认取核心数的 4 倍，但不低于 8 (针对低核服务器优化)
        count = max(8, cpu_count * 4)
    else:
        count = cpu_count

    if max_limit:
        count = min(count, max_limit)

    if task_type == "cpu":
        count = min(count, _env_int("TRENDZEN_CPU_WORKER_LIMIT", 4))
    elif task_type == "io":
        count = min(count, _env_int("TRENDZEN_IO_WORKER_LIMIT", 8))

    return max(1, count)


# ---------------------------------------------------------------------------
# GPU 检测
# ---------------------------------------------------------------------------

_gpu_info_cache: dict | None = None
_gpu_info_lock = threading.Lock()


def _probe_gpu_via_pynvml() -> dict | None:
    """优先使用 pynvml（NVIDIA 官方 Python 绑定）检测 GPU，失败返回 None"""
    try:
        import pynvml  # type: ignore
    except Exception:
        return None
    try:
        pynvml.nvmlInit()
        try:
            device_count = int(pynvml.nvmlDeviceGetCount())
        except Exception:
            return {"available": False, "devices": [], "library": "pynvml", "error": "NVML 初始化成功但无法枚举设备"}
        devices: list[dict] = []
        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode("utf-8", errors="ignore")
            try:
                mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                total_mb = int(mem.total // (1024 * 1024))
                used_mb = int(mem.used // (1024 * 1024))
            except Exception:
                total_mb = 0
                used_mb = 0
            devices.append({
                "name": str(name),
                "memory_total_mb": total_mb,
                "memory_used_mb": used_mb,
            })
        return {
            "available": device_count > 0,
            "devices": devices,
            "library": "pynvml",
            "error": "",
        }
    except Exception as exc:
        return {"available": False, "devices": [], "library": "pynvml", "error": str(exc)}
    finally:
        try:
            pynvml.nvmlShutdown()
        except Exception:
            pass


def _probe_gpu_via_nvidia_smi() -> dict | None:
    """兜底使用 nvidia-smi 命令行检测，无 NVIDIA 驱动或工具不在 PATH 时返回 None"""
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return None
    try:
        result = subprocess.run(
            [
                nvidia_smi,
                "--query-gpu=name,memory.total,memory.used",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as exc:
        return {"available": False, "devices": [], "library": "nvidia-smi", "error": str(exc)}

    if result.returncode != 0:
        return {
            "available": False,
            "devices": [],
            "library": "nvidia-smi",
            "error": (result.stderr or "").strip() or f"exit code {result.returncode}",
        }

    devices: list[dict] = []
    for line in result.stdout.strip().splitlines():
        parts = [item.strip() for item in line.split(",")]
        if len(parts) < 3:
            continue
        try:
            total_mb = int(parts[1])
            used_mb = int(parts[2])
        except Exception:
            total_mb = 0
            used_mb = 0
        devices.append({
            "name": parts[0],
            "memory_total_mb": total_mb,
            "memory_used_mb": used_mb,
        })
    return {
        "available": len(devices) > 0,
        "devices": devices,
        "library": "nvidia-smi",
        "error": "",
    }


def detect_gpu() -> dict:
    """
    检测系统中的 GPU 设备（目前仅支持 NVIDIA）。

    Returns:
        {
            "available": bool,                # 是否检测到可用 GPU
            "devices": [{                     # GPU 设备列表
                "name": str,
                "memory_total_mb": int,
                "memory_used_mb": int,
            }],
            "library": str,                   # 检测方式：pynvml / nvidia-smi / ""
            "error": str,                     # 检测失败原因（用于诊断）
        }
    """
    global _gpu_info_cache
    if _gpu_info_cache is not None:
        return dict(_gpu_info_cache)
    with _gpu_info_lock:
        if _gpu_info_cache is None:
            for probe in (_probe_gpu_via_pynvml, _probe_gpu_via_nvidia_smi):
                result = probe()
                if result is None:
                    continue
                if result.get("available"):
                    _gpu_info_cache = result
                    break
            if _gpu_info_cache is None:
                _gpu_info_cache = {
                    "available": False,
                    "devices": [],
                    "library": "",
                    "error": "未找到 pynvml 或 nvidia-smi，无法检测 GPU",
                }
    return dict(_gpu_info_cache)


# ---------------------------------------------------------------------------
# 运行时并发信息（供前端展示）
# ---------------------------------------------------------------------------

_runtime_info_cache: dict | None = None
_runtime_info_lock = threading.Lock()


def _compute_runtime_info() -> dict:
    cpu_count = os.cpu_count() or 1
    return {
        "cpu_count": cpu_count,
        "cpu_workers_scan": get_optimal_worker_count("cpu", max_limit=16),
        "cpu_workers_backtest": get_optimal_worker_count("cpu", max_limit=8),
        "io_workers_screening": get_optimal_worker_count("io", max_limit=16),
        "io_workers_market": get_optimal_worker_count("io", max_limit=12),
        "io_workers_download": get_optimal_worker_count("io", max_limit=32),
        "cpu_worker_limit_env": _env_int("TRENDZEN_CPU_WORKER_LIMIT", 4),
        "io_worker_limit_env": _env_int("TRENDZEN_IO_WORKER_LIMIT", 8),
    }


def get_runtime_info() -> dict:
    """获取运行时并发信息（带缓存，避免重复探测子进程）"""
    global _runtime_info_cache
    if _runtime_info_cache is not None:
        return dict(_runtime_info_cache)
    with _runtime_info_lock:
        if _runtime_info_cache is None:
            _runtime_info_cache = _compute_runtime_info()
    return dict(_runtime_info_cache)


def refresh_runtime_info() -> dict:
    """强制重新探测运行时信息（用于调试或环境变更后）"""
    global _runtime_info_cache
    with _runtime_info_lock:
        _runtime_info_cache = None
        _runtime_info_cache = _compute_runtime_info()
    return dict(_runtime_info_cache)


# ---------------------------------------------------------------------------
# 实时系统资源（CPU / 内存 / GPU），供前端右下角监控组件轮询
# ---------------------------------------------------------------------------

try:
    import psutil  # type: ignore
    _PSUTIL_AVAILABLE = True
except Exception:
    psutil = None  # type: ignore
    _PSUTIL_AVAILABLE = False

_cpu_percent_seeded = False
_cpu_percent_seed_lock = threading.Lock()


def _seed_cpu_percent() -> None:
    """psutil.cpu_percent 首次调用返回 0.0，需要先调用一次建立基准，后续才有意义。"""
    global _cpu_percent_seeded
    if _cpu_percent_seeded:
        return
    with _cpu_percent_seed_lock:
        if not _cpu_percent_seeded:
            try:
                psutil.cpu_percent(interval=None)
            except Exception:
                pass
            _cpu_percent_seeded = True


def get_live_gpu_stats() -> list[dict]:
    """实时获取每块 GPU 的显存占用与核心利用率（仅支持 NVIDIA，依赖 nvidia-smi 在 PATH）。
    无 nvidia-smi 时回退到 detect_gpu() 的静态信息（仅有名称和总显存，利用率未知）。"""
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        try:
            result = subprocess.run(
                [
                    nvidia_smi,
                    "--query-gpu=name,memory.total,memory.used,utilization.gpu",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception:
            result = None
        if result is not None and result.returncode == 0:
            devices: list[dict] = []
            for line in result.stdout.strip().splitlines():
                parts = [item.strip() for item in line.split(",")]
                if len(parts) < 4:
                    continue
                try:
                    total_mb = int(parts[1])
                except Exception:
                    total_mb = 0
                try:
                    used_mb = int(parts[2])
                except Exception:
                    used_mb = 0
                try:
                    util_pct = float(parts[3])
                except Exception:
                    util_pct = 0.0
                devices.append({
                    "name": parts[0],
                    "memory_total_mb": total_mb,
                    "memory_used_mb": used_mb,
                    "utilization_pct": util_pct,
                })
            if devices:
                return devices

    # 回退：nvidia-smi 不可用时，至少展示静态探测到的 GPU 名称与总显存
    gpu = detect_gpu()
    return [
        {
            "name": device.get("name", "GPU"),
            "memory_total_mb": int(device.get("memory_total_mb", 0) or 0),
            "memory_used_mb": int(device.get("memory_used_mb", 0) or 0),
            "utilization_pct": None,
        }
        for device in (gpu.get("devices") or [])
    ]


def get_system_stats() -> dict:
    """获取实时系统资源占用（跨平台 Win/Linux）。psutil 缺失时返回可用部分。"""
    _seed_cpu_percent()
    stats: dict = {
        "cpu_percent": None,
        "cpu_count": os.cpu_count() or 1,
        "memory_total_bytes": None,
        "memory_used_bytes": None,
        "memory_percent": None,
        "gpu": get_live_gpu_stats(),
        "psutil_available": _PSUTIL_AVAILABLE,
    }
    if not _PSUTIL_AVAILABLE:
        return stats
    try:
        stats["cpu_percent"] = round(float(psutil.cpu_percent(interval=None)), 1)
    except Exception:
        pass
    try:
        vm = psutil.virtual_memory()
        stats["memory_total_bytes"] = int(vm.total)
        stats["memory_used_bytes"] = int(vm.used)
        stats["memory_percent"] = round(float(vm.percent), 1)
    except Exception:
        pass
    try:
        stats["cpu_count"] = psutil.cpu_count(logical=True) or stats["cpu_count"]
    except Exception:
        pass
    return stats
