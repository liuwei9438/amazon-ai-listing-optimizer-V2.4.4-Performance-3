from __future__ import annotations

import os
import shutil
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from services.batch_processor import process_batch
from services.api_metrics import load_api_metrics, reset_api_context, set_api_context
from services.result_storage import (
    load_failed_items,
    load_profiles,
    reconcile_task_results,
    save_failed_items,
    save_profiles,
)
from services.task_control import load_control, save_control
from services.task_manager import get_task_dir, save_status


DEFAULT_MAX_WORKERS = 4
MAX_ALLOWED_WORKERS = 8


def _resolve_max_workers(options: dict | None) -> int:
    raw = options.get("max_workers") if isinstance(options, dict) else None
    if raw in (None, ""):
        raw = os.getenv("AI_MAX_WORKERS", DEFAULT_MAX_WORKERS)
    try:
        workers = int(raw)
    except (TypeError, ValueError):
        workers = DEFAULT_MAX_WORKERS
    return max(1, min(workers, MAX_ALLOWED_WORKERS))


def _child_task_id(task_id: str, index: int) -> str:
    return f"{task_id}/workers/item_{index:05d}"


def _run_one_record(*, record, index, parent_task_id, api_key, model, options):
    """Reuse the stable one-product pipeline in an isolated child directory."""
    child_id = _child_task_id(parent_task_id, index)
    save_control(child_id, "running")
    started = time.time()
    context_tokens = set_api_context(parent_task_id, index)
    try:
        process_batch([record], child_id, api_key, model, options)
        profiles = load_profiles(child_id)
        failed_items = load_failed_items(child_id)
        profile = profiles[0] if profiles else None
        failed = failed_items[0] if failed_items else None

        if profile is None and failed is None:
            failed = {
                "index": index,
                "source_row_index": getattr(record, "row_number", None),
                "sku": getattr(record, "sku", ""),
                "title": getattr(record, "title", ""),
                "error": "并发子任务结束但没有产生成功或失败结果",
                "error_type": "unresolved_concurrent_item",
            }

        if isinstance(failed, dict):
            failed["index"] = index
            failed["source_row_index"] = getattr(record, "row_number", None)

        return {
            "index": index,
            "profile": profile,
            "failed": failed,
            "elapsed": round(time.time() - started, 2),
        }
    except Exception as exc:
        return {
            "index": index,
            "profile": None,
            "failed": {
                "index": index,
                "source_row_index": getattr(record, "row_number", None),
                "sku": getattr(record, "sku", ""),
                "title": getattr(record, "title", ""),
                "error": str(exc),
                "error_type": type(exc).__name__,
            },
            "elapsed": round(time.time() - started, 2),
        }
    finally:
        reset_api_context(context_tokens)


def _cleanup_child(parent_task_id: str, index: int):
    try:
        shutil.rmtree(
            get_task_dir(_child_task_id(parent_task_id, index)),
            ignore_errors=True,
        )
    except OSError:
        pass


def process_batch_concurrent(
    records,
    task_id,
    api_key,
    model="gpt-4.1-mini",
    options=None,
):
    """Bounded product-level concurrency while preserving per-product ordering."""
    if options is None:
        options = {}

    total = len(records)
    max_workers = min(_resolve_max_workers(options), max(total, 1))

    if total == 0:
        save_status(
            task_id,
            {
                "task_id": task_id,
                "status": "completed",
                "message": "没有需要处理的商品",
                "completed": 0,
                "total": 0,
                "success": 0,
                "failed": 0,
                "max_workers": 0,
            },
        )
        return []

    profiles_by_index = {}
    failed_by_index = {}
    next_index = 0
    futures = {}
    cancelled = False

    save_status(
        task_id,
        {
            "task_id": task_id,
            "status": "processing",
            "message": f"并发优化启动：{max_workers} 个产品 Worker",
            "completed": 0,
            "total": total,
            "success": 0,
            "failed": 0,
            "max_workers": max_workers,
        },
    )

    def persist_parent_results():
        ordered_profiles = [
            profiles_by_index[i] for i in sorted(profiles_by_index)
        ]
        ordered_failed = [
            failed_by_index[i] for i in sorted(failed_by_index)
        ]
        save_profiles(task_id, ordered_profiles)
        save_failed_items(task_id, ordered_failed)
        return ordered_profiles, ordered_failed

    with ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix="listing-product",
    ) as executor:
        while next_index < total or futures:
            action = load_control(task_id)

            if action == "cancel":
                cancelled = True

            if action == "pause" and not cancelled:
                save_status(
                    task_id,
                    {
                        "status": "paused",
                        "message": "任务已暂停；运行中的商品会先安全结束，不再提交新商品",
                        "completed": len(profiles_by_index) + len(failed_by_index),
                        "total": total,
                        "success": len(profiles_by_index),
                        "failed": len(failed_by_index),
                        "in_flight": len(futures),
                    },
                )

            while (
                not cancelled
                and action != "pause"
                and next_index < total
                and len(futures) < max_workers
            ):
                record = records[next_index]
                future = executor.submit(
                    _run_one_record,
                    record=record,
                    index=next_index,
                    parent_task_id=task_id,
                    api_key=api_key,
                    model=model,
                    options=options,
                )
                futures[future] = next_index
                next_index += 1

            if not futures:
                if cancelled:
                    break
                if action == "pause":
                    time.sleep(0.4)
                    continue
                if next_index >= total:
                    break
                continue

            done, _ = wait(
                list(futures),
                timeout=0.5,
                return_when=FIRST_COMPLETED,
            )
            if not done:
                continue

            for future in done:
                index = futures.pop(future)
                result = future.result()
                if result.get("profile") is not None:
                    profiles_by_index[index] = result["profile"]
                    failed_by_index.pop(index, None)
                else:
                    failed_by_index[index] = result["failed"]
                _cleanup_child(task_id, index)

            ordered_profiles, ordered_failed = persist_parent_results()
            completed = len(ordered_profiles) + len(ordered_failed)

            api_metrics = load_api_metrics(task_id)
            save_status(
                task_id,
                {
                    "task_id": task_id,
                    "status": "processing" if not cancelled else "cancelling",
                    "message": (
                        f"并发处理中：{completed}/{total}，"
                        f"运行中 {len(futures)}，并发 {max_workers}"
                    ),
                    "completed": completed,
                    "total": total,
                    "success": len(ordered_profiles),
                    "failed": len(ordered_failed),
                    "in_flight": len(futures),
                    "max_workers": max_workers,
                    "api_calls": api_metrics.get("total_calls", 0),
                    "api_attempts": api_metrics.get("total_attempts", 0),
                    "api_retries": api_metrics.get("retry_attempts", 0),
                },
            )

    persist_parent_results()

    if cancelled:
        reconciliation = reconcile_task_results(
            task_id,
            records,
            unresolved_error="任务已取消，该商品尚未开始处理",
        )
        api_metrics = load_api_metrics(task_id)
        save_status(
            task_id,
            {
                "task_id": task_id,
                "status": "cancelled",
                "message": "任务已取消",
                "completed": reconciliation["completed"],
                "total": total,
                "success": reconciliation["success"],
                "failed": reconciliation["failed"],
                "in_flight": 0,
                "max_workers": max_workers,
                "api_calls": api_metrics.get("total_calls", 0),
                "api_attempts": api_metrics.get("total_attempts", 0),
                "api_retries": api_metrics.get("retry_attempts", 0),
            },
        )
        return reconciliation["profiles"]

    reconciliation = reconcile_task_results(
        task_id,
        records,
        unresolved_error="并发任务未产生成功或失败结果，已由闭环检查记录为失败",
    )
    api_metrics = load_api_metrics(task_id)
    save_status(
        task_id,
        {
            "task_id": task_id,
            "status": "completed",
            "message": "任务完成",
            "completed": reconciliation["completed"],
            "total": total,
            "success": reconciliation["success"],
            "failed": reconciliation["failed"],
            "in_flight": 0,
            "max_workers": max_workers,
            "api_calls": api_metrics.get("total_calls", 0),
            "api_attempts": api_metrics.get("total_attempts", 0),
            "api_retries": api_metrics.get("retry_attempts", 0),
        },
    )
    return reconciliation["profiles"]
