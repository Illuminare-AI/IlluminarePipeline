"""Run the native backend, image service and frontend together; Ctrl+C stops all three."""
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    node = shutil.which('node')
    vite = ROOT / 'frontend/node_modules/vite/bin/vite.js'
    if (not node or not vite.is_file() or not (ROOT / '.env').is_file()
            or not (ROOT / 'frontend/image-context/.env').is_file()):
        print('Run scripts/setup.cmd first (or follow README-QUICKSTART.md on Linux).')
        return 1
    for port in (8000, 8001, 5173):
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1', port))
            except OSError:
                print(f'Port {port} is already in use. Stop the existing service before starting.')
                return 1
    commands = [
        ([sys.executable, '-m', 'uvicorn', 'image_context.api:app', '--host', '127.0.0.1',
          '--port', '8001', '--env-file', str(ROOT / 'frontend/image-context/.env')], ROOT),
        ([sys.executable, '-m', 'uvicorn', 'factcheck.api:app', '--host', '127.0.0.1',
          '--port', '8000', '--env-file', str(ROOT / '.env')], ROOT),
        ([node, str(vite), '--host', '127.0.0.1', '--port', '5173', '--strictPort'],
         ROOT / 'frontend'),
    ]
    processes = []
    try:
        for command, cwd in commands:
            processes.append(subprocess.Popen(command, cwd=cwd))
        print('App: http://localhost:5173 | Ctrl+C stops all three services.', flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(0.5)
        print('A service exited. Stopping the remaining services.', flush=True)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == '__main__':
    sys.exit(main())
