"""
Creates a Windows Task Scheduler task that runs main.py daily at 5pm.
Run this script once as Administrator (or it will prompt for elevation).
"""

import subprocess
import sys
from pathlib import Path

TASK_NAME = "JobListingsHunter"
SCRIPT_PATH = Path(__file__).parent / "main.py"
PYTHON_EXE = sys.executable  # same Python that's running this script


def create_task():
    cmd = [
        "schtasks", "/Create",
        "/TN", TASK_NAME,
        "/TR", f'"{PYTHON_EXE}" "{SCRIPT_PATH}"',
        "/SC", "DAILY",
        "/ST", "17:00",
        "/F",  # overwrite if exists
        "/RL", "HIGHEST",
    ]

    print(f"Creating task '{TASK_NAME}' — runs daily at 17:00")
    print(f"  Python:  {PYTHON_EXE}")
    print(f"  Script:  {SCRIPT_PATH}")
    print()

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print("Task created successfully.")
        print("To verify: open Task Scheduler and look for 'JobListingsHunter'")
        print("To run now: schtasks /Run /TN JobListingsHunter")
    else:
        print("Failed to create task:")
        print(result.stderr or result.stdout)
        sys.exit(1)


def delete_task():
    result = subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(f"Task '{TASK_NAME}' deleted.")
    else:
        print(result.stderr or result.stdout)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "delete":
        delete_task()
    else:
        create_task()
