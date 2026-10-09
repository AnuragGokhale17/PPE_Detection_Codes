"""
Retraining daemon.

Picks queued training_runs (created by admins in the portal), pauses inference so the
run has the A40 to itself, mirrors the dataset version from object storage, fine-tunes
with Ultralytics, evaluates the new weights AND the active model on the same validation
split, and registers the result in model_versions. Promotion stays a manual step in the
portal (it sets runtime_state.active_model_id; inference.py hot-swaps the weights).

    python trainer.py
"""
import logging
import shutil
import signal
import sys
import threading
import time
import traceback
from contextlib import contextmanager

import worker_common as wc
from worker_logic import (
    TRAINER_PAUSE_PREFIX,
    RollingLog,
    build_data_yaml,
    build_progress,
    parse_train_params,
    same_class_names,
    summarize_class_results,
    trainer_owns_pause,
)

log = logging.getLogger("trainer")

POLL_SECONDS = wc.env_float("TRAINER_POLL_SECONDS", 10)
PAUSE_WAIT_SECONDS = wc.env_float("TRAINER_PAUSE_WAIT_SECONDS", 180)
INFERENCE_STALE_SECONDS = 120  # no inference heartbeat for this long = inference isn't running
LOG_FLUSH_SECONDS = 15
KEEP_DATASET_COPIES = wc.env_bool("TRAINER_KEEP_DATASETS", False)

RUNS_DIR = wc.REPO_DIR / "training" / "runs"
MODELS_DIR = wc.REPO_DIR / "model" / "versions"

shutdown_event = threading.Event()


class TrainingCancelled(Exception):
    pass


# ==============================================================================
# CONSOLE CAPTURE (training output -> training_runs.log_tail)
# ==============================================================================
class Tee:
    """Writes through to the real stream and copies into the current run's RollingLog.
    Installed once at startup, before ultralytics is imported, so its logger binds to it."""

    def __init__(self, stream, lock):
        self.stream = stream
        self.buffer = None
        self.lock = lock

    def write(self, s):
        self.stream.write(s)
        with self.lock:
            if self.buffer is not None:
                self.buffer.write(s)
        return len(s)

    def flush(self):
        self.stream.flush()

    def isatty(self):
        return False

    def __getattr__(self, name):
        return getattr(self.stream, name)


# stdout and stderr feed the same RollingLog, so they share one lock
CAPTURE_LOCK = threading.Lock()
TEE_OUT = Tee(sys.stdout, CAPTURE_LOCK)
TEE_ERR = Tee(sys.stderr, CAPTURE_LOCK)


def capture_into(buffer):
    with CAPTURE_LOCK:
        TEE_OUT.buffer = buffer
        TEE_ERR.buffer = buffer


def captured_text(buffer):
    with CAPTURE_LOCK:
        return buffer.text()


# ==============================================================================
# DATABASE HELPERS
# ==============================================================================
@contextmanager
def cursor(dict_rows=False):
    from psycopg2.extras import RealDictCursor

    conn = wc.connect()
    try:
        with conn.cursor(cursor_factory=RealDictCursor if dict_rows else None) as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_run(run_id, **fields):
    from psycopg2.extras import Json

    if not fields:
        return
    cols = ", ".join(f"{k} = %s" for k in fields)
    values = [Json(v) if isinstance(v, (dict, list)) else v for v in fields.values()]
    with cursor() as cur:
        cur.execute(f"UPDATE training_runs SET {cols} WHERE id = %s", (*values, run_id))


def finish_run(run_id, status, **fields):
    with cursor() as cur:
        cur.execute("SELECT now()")
        now = cur.fetchone()[0]
    update_run(run_id, status=status, finished_at=now, **fields)


def recover_on_startup():
    """A run left 'running' means the trainer died mid-run; also release its inference pause."""
    with cursor() as cur:
        cur.execute(
            "UPDATE training_runs SET status = 'failed', error = 'Trainer restarted during the run', "
            "finished_at = now() WHERE status = 'running' RETURNING id"
        )
        stale = [r[0] for r in cur.fetchall()]
        cur.execute(
            "UPDATE runtime_state SET inference_paused = false, pause_reason = NULL, "
            "updated_by = 'trainer', updated_at = now() "
            "WHERE id = 1 AND inference_paused AND pause_reason LIKE %s RETURNING id",
            (TRAINER_PAUSE_PREFIX + "%",),
        )
        released = cur.fetchone() is not None
    if stale:
        log.warning("Marked interrupted runs as failed: %s", stale)
    if released:
        log.warning("Released an inference pause left by a previous trainer process.")


def claim_next_run():
    with cursor(dict_rows=True) as cur:
        cur.execute(
            """
            UPDATE training_runs
               SET status = 'running', started_at = now(), error = NULL
             WHERE id = (
                   SELECT id FROM training_runs
                    WHERE status = 'queued'
                    ORDER BY created_at, id
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED)
            RETURNING id, dataset_version_id, base_model_id, params, cancel_requested
            """
        )
        return cur.fetchone()


def has_queued_runs():
    with cursor() as cur:
        cur.execute("SELECT EXISTS (SELECT 1 FROM training_runs WHERE status = 'queued')")
        return cur.fetchone()[0]


def cancel_requested(run_id):
    with cursor() as cur:
        cur.execute("SELECT cancel_requested FROM training_runs WHERE id = %s", (run_id,))
        row = cur.fetchone()
    return bool(row and row[0])


def fetch_one(sql, params):
    with cursor(dict_rows=True) as cur:
        cur.execute(sql, params)
        return cur.fetchone()


# ==============================================================================
# INFERENCE PAUSE (shared GPU)
# ==============================================================================
def pause_inference(run_id):
    """Pauses inference for this run. Returns False when an admin had already paused it
    for another reason (that pause is theirs to lift, not ours)."""
    with cursor() as cur:
        cur.execute("SELECT inference_paused, pause_reason FROM runtime_state WHERE id = 1 FOR UPDATE")
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("runtime_state is missing; run `alembic upgrade head` in backend/")
        paused, reason = row
        if paused and not trainer_owns_pause(reason):
            log.info("Inference already paused by someone else (%s); leaving that pause in place.", reason)
            return False
        cur.execute(
            "UPDATE runtime_state SET inference_paused = true, pause_reason = %s, "
            "updated_by = 'trainer', updated_at = now() WHERE id = 1",
            (f"{TRAINER_PAUSE_PREFIX}{run_id}",),
        )
    log.info("Inference paused for run #%s.", run_id)
    return True


def resume_inference_if_ours():
    if has_queued_runs():
        log.info("More runs are queued; inference stays paused.")
        return
    with cursor() as cur:
        cur.execute(
            "UPDATE runtime_state SET inference_paused = false, pause_reason = NULL, "
            "updated_by = 'trainer', updated_at = now() "
            "WHERE id = 1 AND inference_paused AND pause_reason LIKE %s RETURNING id",
            (TRAINER_PAUSE_PREFIX + "%",),
        )
        resumed = cur.fetchone() is not None
    if resumed:
        log.info("Inference resumed.")


def wait_for_inference_pause(run_id, cancel_event):
    """Waits until inference reports 'paused' (GPU released) or is evidently not running."""
    deadline = time.time() + PAUSE_WAIT_SECONDS
    while time.time() < deadline:
        if cancel_event.is_set():
            raise TrainingCancelled()
        row = fetch_one(
            "SELECT EXTRACT(EPOCH FROM (now() - last_seen)) AS age, info "
            "FROM worker_heartbeats WHERE name = 'inference'",
            (),
        )
        if row is None:
            return
        if float(row["age"]) > INFERENCE_STALE_SECONDS:
            log.info("Inference heartbeat is %.0fs old; assuming it is not running.", float(row["age"]))
            return
        if (row["info"] or {}).get("state") in ("paused", "stopped"):
            log.info("Inference confirmed paused for run #%s.", run_id)
            return
        time.sleep(5)
    log.warning("Inference did not confirm the pause within %ss; training anyway.", PAUSE_WAIT_SECONDS)


# ==============================================================================
# TRAINING & EVALUATION (ultralytics imported lazily)
# ==============================================================================
def evaluate(weights, data_yaml, params, out_dir, tag):
    """Validation metrics in the shape the portal shows (see summarize_class_results)."""
    from ultralytics import YOLO

    batch = params["batch"] if params["batch"] > 0 else 16
    res = YOLO(str(weights)).val(
        data=str(data_yaml),
        split="val",
        imgsz=params["imgsz"],
        batch=batch,
        device=params["device"],
        workers=params["workers"],
        plots=False,
        verbose=False,
        project=str(out_dir),
        name=f"val_{tag}",
        exist_ok=True,
    )
    box = res.box
    raw_idx = getattr(box, "ap_class_index", None)
    idx = [] if raw_idx is None else [int(i) for i in raw_idx]
    class_results = [box.class_result(i) for i in range(len(idx))]
    names = {int(k): v for k, v in (res.names or {}).items()}
    return summarize_class_results(names, idx, class_results, box.mean_results())


def train(run_id, weights, data_yaml, params, run_dir, cancel_event):
    from ultralytics import YOLO

    model = YOLO(str(weights))
    history = []

    def on_fit_epoch_end(trainer):
        progress = build_progress(trainer.epoch + 1, trainer.epochs, getattr(trainer, "metrics", {}), history)
        update_run(run_id, progress=progress)
        m = progress["metrics"]
        log.info("Run #%s epoch %s/%s mAP50-95=%s mAP50=%s", run_id, progress["epoch"], progress["epochs"],
                 m["map50_95"], m["map50"])
        if cancel_event.is_set():
            raise TrainingCancelled()

    def on_train_batch_end(_trainer):
        if cancel_event.is_set():
            raise TrainingCancelled()

    model.add_callback("on_fit_epoch_end", on_fit_epoch_end)
    model.add_callback("on_train_batch_end", on_train_batch_end)

    kwargs = dict(
        data=str(data_yaml),
        epochs=params["epochs"],
        imgsz=params["imgsz"],
        batch=params["batch"],
        patience=params["patience"],
        workers=params["workers"],
        device=params["device"],
        project=str(run_dir),
        name="train",
        exist_ok=True,
        # The GPU server is offline: plotting makes Ultralytics fetch a font from the internet
        plots=False,
    )
    if params["lr0"] is not None:
        kwargs["lr0"] = params["lr0"]
    model.train(**kwargs)

    weights_dir = run_dir / "train" / "weights"
    for candidate in ("best.pt", "last.pt"):
        if (weights_dir / candidate).exists():
            return weights_dir / candidate
    raise RuntimeError(f"Training finished but no weights were written to {weights_dir}")


def register_model(run_id, best, class_names, metrics, notes):
    """Copies the weights to model/versions/<id>/best.pt and inserts model_versions (inactive)."""
    from psycopg2.extras import Json

    conn = wc.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO model_versions (name, weights_path, class_names, metrics, source, training_run_id,
                                            is_active, notes)
                VALUES (%s, 'pending', %s, %s, 'training', %s, false, %s)
                RETURNING id
                """,
                (f"run-{run_id}", Json(class_names), Json(metrics), run_id, notes),
            )
            model_id = cur.fetchone()[0]
            dest = MODELS_DIR / str(model_id) / "best.pt"
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(best, dest)
            cur.execute(
                "UPDATE model_versions SET weights_path = %s WHERE id = %s",
                (dest.relative_to(wc.REPO_DIR).as_posix(), model_id),
            )
        conn.commit()
        return model_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def process_run(run):
    run_id = run["id"]
    params = parse_train_params(run["params"])
    run_dir = RUNS_DIR / str(run_id)
    dataset_dir = run_dir / "dataset"
    buffer = RollingLog(8000)
    cancel_event = threading.Event()
    done = threading.Event()
    stopped_by_service = False

    def flusher():
        while not done.wait(LOG_FLUSH_SECONDS):
            try:
                update_run(run_id, log_tail=captured_text(buffer))
                if cancel_requested(run_id):
                    cancel_event.set()
                if shutdown_event.is_set():
                    cancel_event.set()
                wc.heartbeat(None, "trainer", {"state": "running", "run_id": run_id})
            except Exception as e:
                log.warning("Progress flush failed: %s", e)

    capture_into(buffer)
    flush_thread = threading.Thread(target=flusher, name="flusher", daemon=True)
    flush_thread.start()
    wc.heartbeat(None, "trainer", {"state": "running", "run_id": run_id})
    log.info("Run #%s started with %s", run_id, params)

    paused_by_us = False
    try:
        if run.get("cancel_requested"):
            raise TrainingCancelled()
        paused_by_us = pause_inference(run_id)
        wait_for_inference_pause(run_id, cancel_event)

        dataset = fetch_one(
            "SELECT id, name, status, s3_prefix, class_names FROM dataset_versions WHERE id = %s",
            (run["dataset_version_id"],),
        )
        if dataset is None or dataset["status"] != "ready":
            raise RuntimeError(f"Dataset version {run['dataset_version_id']} is not ready")
        base = fetch_one("SELECT id, name, weights_path FROM model_versions WHERE id = %s", (run["base_model_id"],))
        if base is None:
            raise RuntimeError(f"Base model {run['base_model_id']} not found")
        base_weights = wc.resolve_repo_path(base["weights_path"])
        if not base_weights.exists():
            raise FileNotFoundError(f"Base weights not found: {base_weights}")
        class_names = list(dataset["class_names"] or [])
        if not class_names:
            raise RuntimeError("Dataset version has no class names")

        # Mirror the dataset version locally and point data.yaml at it
        if dataset_dir.exists():
            shutil.rmtree(dataset_dir)
        dataset_dir.mkdir(parents=True)
        count = wc.get_storage().download_prefix(dataset["s3_prefix"], dataset_dir)
        log.info("Downloaded %d dataset files from %s", count, dataset["s3_prefix"])
        if not (dataset_dir / "images" / "train").is_dir() or not (dataset_dir / "images" / "val").is_dir():
            raise RuntimeError("Dataset is missing images/train or images/val")
        data_yaml = dataset_dir / "data.yaml"
        data_yaml.write_text(build_data_yaml(dataset_dir.resolve().as_posix(), class_names), encoding="utf-8")

        if cancel_event.is_set():
            raise TrainingCancelled()
        best = train(run_id, base_weights, data_yaml, params, run_dir, cancel_event)

        log.info("Evaluating run #%s weights on the validation split...", run_id)
        metrics = evaluate(best, data_yaml, params, run_dir, "new")

        # The active model on the same split, so admins compare like for like
        baseline = {"skipped": "No active model"}
        active = fetch_one(
            "SELECT mv.id, mv.name, mv.weights_path, mv.class_names FROM runtime_state rs "
            "JOIN model_versions mv ON mv.id = rs.active_model_id WHERE rs.id = 1",
            (),
        )
        if active is not None:
            active_weights = wc.resolve_repo_path(active["weights_path"])
            if not active_weights.exists():
                baseline = {"skipped": f"Active model weights not found ({active['weights_path']})"}
            elif not same_class_names(active["class_names"], class_names):
                baseline = {"skipped": "Active model's classes differ from this dataset's classes"}
            else:
                log.info("Evaluating the active model (%s) on the same split...", active["name"])
                baseline = evaluate(active_weights, data_yaml, params, run_dir, "active")
                baseline["model_id"] = active["id"]

        model_id = register_model(
            run_id, best, class_names, metrics,
            notes=f"Fine-tuned from {base['name']} on dataset {dataset['name']}",
        )
        text = captured_text(buffer)
        finish_run(run_id, "succeeded", metrics=metrics, baseline_metrics=baseline,
                   result_model_id=model_id, log_tail=text)
        log.info("Run #%s succeeded -> model_versions #%s (mAP50-95 %s vs active %s)",
                 run_id, model_id, metrics.get("map50_95"), baseline.get("map50_95", "n/a"))

    except TrainingCancelled:
        stopped_by_service = shutdown_event.is_set() and not cancel_requested(run_id)
        text = captured_text(buffer)
        if stopped_by_service:
            finish_run(run_id, "failed", error="Trainer service stopped during the run", log_tail=text)
        else:
            finish_run(run_id, "cancelled", log_tail=text)
        log.warning("Run #%s %s.", run_id, "interrupted by shutdown" if stopped_by_service else "cancelled")
    except Exception as e:
        log.error("Run #%s failed: %s", run_id, e)
        buffer.write("\n" + traceback.format_exc())
        text = captured_text(buffer)
        try:
            finish_run(run_id, "failed", error=str(e)[:4000], log_tail=text)
        except Exception as e2:
            log.error("Could not record the failure of run #%s: %s", run_id, e2)
    finally:
        done.set()
        flush_thread.join(timeout=5)
        capture_into(None)
        if not KEEP_DATASET_COPIES and dataset_dir.exists():
            shutil.rmtree(dataset_dir, ignore_errors=True)
        if paused_by_us:
            try:
                resume_inference_if_ours()
            except Exception as e:
                log.error("Could not resume inference: %s", e)
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass


# ==============================================================================
# MAIN LOOP
# ==============================================================================
def main():
    # Route console output through the tees before ultralytics is imported
    sys.stdout, sys.stderr = TEE_OUT, TEE_ERR
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)

    def _handle_signal(signum, _frame):
        log.info("Received signal %s; stopping after the current step.", signum)
        shutdown_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    recover_on_startup()
    log.info("Trainer ready; polling for queued runs every %ss.", POLL_SECONDS)

    while not shutdown_event.is_set():
        try:
            wc.heartbeat(None, "trainer", {"state": "idle", "run_id": None})
            run = claim_next_run()
            if run is not None:
                process_run(run)
                continue
        except Exception as e:
            log.exception("Trainer loop error: %s", e)
        shutdown_event.wait(POLL_SECONDS)

    wc.heartbeat(None, "trainer", {"state": "stopped", "run_id": None})
    log.info("Trainer stopped.")


if __name__ == "__main__":
    main()
