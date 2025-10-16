import subprocess
import platform
import os
import gettext
import locale
import shlex
import threading
import fcntl
import time
from gi.repository import GLib

def setup_localisation():
    APP_NAME = "msvsphere-nautilus-extensions"
    LOCALE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "po")
    locale.bindtextdomain(APP_NAME, LOCALE_DIR)
    gettext.bindtextdomain(APP_NAME, LOCALE_DIR)
    gettext.textdomain(APP_NAME)
    return gettext.gettext

def time_to_integer(timef: str = '0', sec=False, rnd=False) -> int:
    """
    Converts strings representing the 24-hour format to an
    integer equivalent to the time duration in milliseconds
    """
    if not isinstance(timef, str):
        raise TypeError("Only a string (str) object is expected.")

    hours, minutes, seconds = (["0", "0"] + timef.split(":"))[-3:]

    try:
        hours = int(hours)
        minutes = int(minutes)
        seconds = float(seconds)
        if rnd:
            seconds = round(seconds)
    except ValueError:
        return 0

    if sec:
        return int(hours * 3600 + minutes * 60 + seconds)
    return int(hours * 3600000 + minutes * 60000 + seconds * 1000)


def integer_to_time(integer: int = 0, mills=True, rnd=False) -> str:
    """
    Converts integers to 24-hour clock format calculating in
    more apropriate format.
    """
    if not isinstance(integer, int):
        raise TypeError("An integer (int) object is expected.")

    minutes, sec = divmod(integer, 60000)
    hours, minutes = divmod(minutes, 60)

    if mills:
        seconds = float(sec) / 1000
        return f"{hours:02}:{minutes:02}:{seconds:06.3f}"

    if rnd:
        seconds = round(sec / 1000)
    else:
        seconds = int(sec / 1000)

    return f"{hours:02}:{minutes:02}:{seconds:02}"


def pairwise(iterable):
    """
    Return a zip object from iterable.
    """
    itobj = iter(iterable)
    return zip(itobj, itobj)


class Popen(subprocess.Popen):
    """
    Inherit subprocess.Popen class to set _startupinfo.
    """
    _startupinfo = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs, startupinfo=self._startupinfo)


def ffmpeg_cmd_args():
    """
    Get ffmpeg command and default args
    """
    cmd = ["ffmpeg"]
    if platform.system() == 'Linux':
        cmd = ["stdbuf", "-e0", "ffmpeg"]
    return {"ffmpeg_cmd": cmd,
            "ffmpeg-default-args": "-y -stats -hide_banner -loglevel info"}

def simple_one_pass(*args, **kwa):
    """
    Command builder for one pass
    """
    _ = setup_localisation()
    cmd = ffmpeg_cmd_args()
    pass1 = (cmd["ffmpeg_cmd"] +
             cmd["ffmpeg-default-args"].split() +
             kwa.get("pre-input-1", "").split() +
             kwa["start-time"].split() +
             ["-i", kwa["source"]] +
             kwa["end-time"].split() +
             kwa["args"][0].split() +
             kwa.get("volume", "").split() +
             [kwa["destination"]])

    count1 = (_("File {0}/{1}\nSource: \"{2}\"\nDestination: \"{3}\" ").format(args[0], args[1], kwa["source"], kwa["destination"]))
    stamp1 = f'{count1}\n\n[COMMAND]:\n{" ".join(shlex.quote(arg) for arg in pass1)}'

    return {'pass1': pass1, 'count1': count1, 'stamp1': stamp1}


class FFmpeg(threading.Thread):

    def __init__(self, window, progress_queue, *args):
        """
        Called from `AudioConverterWindow`.
        """
        self.window = window
        self.progress_queue = progress_queue
        self.stop_work_thread = False
        self.kwargs = args[0]
        self.nargs = len(self.kwargs)
        self.count = 0

        threading.Thread.__init__(self)
        self.start()

    def run(self):
        """
        Run the separated thread.
        """
        filedone = []
        for kwa in self.kwargs:
            self.count += 1
            model = simple_one_pass(self.count, self.nargs, **kwa)

            GLib.idle_add(self.window.update_count, model['count1'], kwa['duration'], 'CONTINUE')

            try:
                proc1 = Popen(model['pass1'],
                              stderr=subprocess.PIPE,
                              stdin=subprocess.PIPE,
                              encoding='utf-8',
                              universal_newlines=True)

                fd = proc1.stderr.fileno()
                fl = fcntl.fcntl(fd, fcntl.F_GETFL)
                fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

                line_buffer = ""
                while proc1.poll() is None:
                    try:
                        data = proc1.stderr.read()
                        if data:
                            line_buffer += data
                            if '\r' in line_buffer or '\n' in line_buffer:
                                lines = line_buffer.replace('\r', '\n').split('\n')
                                line_buffer = lines.pop()
                                for line in lines:
                                    if line:
                                        self.progress_queue.put({'line': line, 'duration': kwa['duration'], 'status': 0})
                    except (TypeError, BlockingIOError):
                        time.sleep(0.05)

                    if self.stop_work_thread:
                        proc1.stdin.write('q')
                        proc1.wait()
                        GLib.idle_add(self.window.update_output, 'STOP', kwa['duration'], 1)
                        time.sleep(.5)
                        GLib.idle_add(self.window.end_conversion, None)
                        return
                
                if line_buffer:
                    self.progress_queue.put({'line': line_buffer, 'duration': kwa['duration'], 'status': 0})

                if proc1.returncode != 0:
                    GLib.idle_add(self.window.update_output, 'FAILED', kwa['duration'], proc1.returncode)
                    time.sleep(1)
                    continue

            except (OSError, FileNotFoundError) as err:
                GLib.idle_add(self.window.update_count, str(err), 0, 'ERROR')
                break

            if proc1.returncode == 0:
                filedone.append(kwa["source"])
                GLib.idle_add(self.window.update_count, '', kwa['duration'], 'DONE')

        time.sleep(.5)
        GLib.idle_add(self.window.end_conversion, filedone)

    def stop(self):
        self.stop_work_thread = True
