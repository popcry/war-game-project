#!/usr/bin/env python3
"""deployment JSON으로 sim 한 번 돌리는 헬퍼 — config.yaml 임시 swap.

사용법:
  python tools/run_with_deployment.py deployments/3_1_..._custom_art.json --max-time 60

config.yaml은 자동 백업/복원되므로 인터럽트해도 안전.
"""
from __future__ import annotations
import argparse, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

import yaml

# launcher의 apply 로직 재사용
sys.path.insert(0, str(Path(__file__).resolve().parent))
from wargame_launcher import apply_deployment_to_config, write_trench_mask  # noqa


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("deployment", help="deployment JSON 경로")
    parser.add_argument("--max-time", type=float, default=60)
    parser.add_argument("--no-video", action="store_true", default=True)
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--show-stdout", action="store_true",
                        help="sim stdout을 그대로 출력 (BFS 로그 등 모두)")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    os.chdir(root)
    deployment = json.loads(Path(args.deployment).read_text())
    cfg = yaml.safe_load(Path("config.yaml").read_text())
    new_cfg = apply_deployment_to_config(cfg, deployment)

    # 임시 워크스페이스에 trench mask 작성
    trench_path = root / "launcher_trench_mask.csv"
    trench = write_trench_mask(deployment, trench_path)
    if trench:
        new_cfg["terrain"]["trench_mask_file"] = trench.name

    # config.yaml swap (try/finally로 원본 복원 보장)
    backup = Path(tempfile.mkdtemp(prefix="wg_cfg_")) / "config.yaml"
    shutil.copy("config.yaml", backup)
    try:
        with open("config.yaml", "w", encoding="utf-8") as f:
            yaml.safe_dump(new_cfg, f, allow_unicode=True, sort_keys=False)

        env = {**os.environ, "SDL_VIDEODRIVER": "dummy"}
        cmd = [
            sys.executable, "-u", "simulation.py",
            "--headless", "--max-time", str(args.max_time),
            "--no-hold", "--no-video",
        ]
        print(f"[run_with_deployment] {Path(args.deployment).name}: "
              f"{sum(len(p) for ts in new_cfg['initial_positions'].values() for p in ts.values())} 유닛")
        result = subprocess.run(cmd, env=env, capture_output=not args.show_stdout)
        if not args.show_stdout:
            # 핵심 로그만 추출
            for line in (result.stdout or b"").decode().splitlines():
                if any(k in line for k in ("Progress", "saved", "Fire:", "Damage:", "BFS", "ended at")):
                    print(line)
        return result.returncode
    finally:
        shutil.copy(backup, "config.yaml")
        backup.unlink(missing_ok=True)
        if trench_path.exists():
            trench_path.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
