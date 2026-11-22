"""File-backed pytest entry point; safe with Windows multiprocessing spawn."""
import multiprocessing
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    import os
    import pytest
    from core.cuda_environment import prepare_native_cuda

    os.chdir(ROOT)
    prepare_native_cuda()
    # GPU sessions preload ONNX libraries themselves. CPU-only acceptance does
    # not require ONNX Runtime or CUDA to be installed.
    return pytest.main(sys.argv[1:] or ["-q", "-rs"])


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
