"""Filter the environment for HyperFrames and its package/browser setup."""

import os
import subprocess
import sys

# Keep the main HyperFrames worker's credential markers and cover connection and registry credentials.
_SECRET_MARKS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "SUPABASE", "DATABASE_URL", "DSN", "AUTH")


def hyperframes_env() -> dict[str, str]:
    env = {name: value for name, value in os.environ.items()
           if not any(mark in name.upper() for mark in _SECRET_MARKS)}
    return {**env, "HYPERFRAMES_NO_TELEMETRY": "1"}


if __name__ == "__main__":
    raise SystemExit(subprocess.run(sys.argv[1:], env=hyperframes_env()).returncode)
