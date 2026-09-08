"""Self-checks for the two reported bugs. Run: python3 test_extensions.py"""
import importlib.util
import os
import queue
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'extensions'))

import common


def load(name):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'extensions', name)
    spec = importlib.util.spec_from_file_location(name.replace('-', '_')[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_mkv_is_detected():
    """shared-mime-info renamed video/x-matroska to video/matroska."""
    sub = load('nautilus-subtitle-combiner.py')
    assert sub.mime_is('video/matroska', 'video/matroska')
    assert sub.mime_is('video/x-matroska', 'video/matroska')
    assert not sub.mime_is('video/webm', 'video/matroska')
    assert not sub.mime_is('video/mp4', 'video/matroska')
    assert sub.mime_is('video/x-m4v', *sub.SUBTITLE_CAPABLE_MIME_TYPES)
    assert not sub.mime_is('video/vnd.avi', *sub.SUBTITLE_CAPABLE_MIME_TYPES)


def test_final_stats_line_is_delivered():
    """A fast ffmpeg job prints its only stats line as it exits; the reader
    must drain the pipe to EOF instead of stopping at process exit."""
    if not subprocess.run(['which', 'ffmpeg'], capture_output=True).returncode == 0:
        print('skip: no ffmpeg')
        return

    q = queue.Queue()
    kwa = {
        'source': 'lavfi',
        'destination': '/dev/null',
        'duration': 3000,
        'args': ['-t 3 -c:v libx264 -f matroska'],
    }
    worker = common.FFmpeg(q, [kwa], cmd_builder=lambda *a, **k: {
        'pass1': common.FFMPEG_CMD + common.FFMPEG_DEFAULT_ARGS.split() + [
            '-f', 'lavfi', '-i', 'testsrc=size=320x240:rate=25',
            '-t', '3', '-c:v', 'libx264', '-f', 'matroska', '/dev/null'],
        'count1': 'test',
    })
    worker.start()
    worker.join(timeout=60)

    lines = []
    done = False
    while not q.empty():
        msg = q.get_nowait()
        if msg['type'] == 'output':
            lines.append(msg['line'])
        if msg['type'] == 'count' and msg['status'] is common.Status.DONE:
            done = True
    assert done, 'conversion did not report DONE'
    assert any('time=' in line for line in lines), 'no progress line reached the UI'


def test_time_conversion():
    assert common.time_to_integer('00:00:02.50') == 2500
    assert common.time_to_integer('N/A') == 0
    assert common.integer_to_time(2500, mills=False) == '00:00:02'


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
