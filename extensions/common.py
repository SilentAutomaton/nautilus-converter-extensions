import subprocess
import os
import re
import gettext
import locale
import shlex
import threading
import fcntl
import time
import queue
from enum import Enum

from gi.repository import Gtk, GLib, Pango


def setup_localisation():
    APP_NAME = "msvsphere-nautilus-extensions"
    local_locale_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "po")
    system_locale_dir = "/usr/share/locale"
    if os.path.isdir(local_locale_dir):
        LOCALE_DIR = local_locale_dir
    else:
        LOCALE_DIR = system_locale_dir
    locale.bindtextdomain(APP_NAME, LOCALE_DIR)
    gettext.bindtextdomain(APP_NAME, LOCALE_DIR)
    gettext.textdomain(APP_NAME)
    return gettext.gettext


_ = setup_localisation()


class Status(Enum):
    CONTINUE = "CONTINUE"
    DONE = "DONE"
    ERROR = "ERROR"
    STOP = "STOP"
    FAILED = "FAILED"


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


_RE_TIME = re.compile(r'time=(\S+)')
_RE_SPEED = re.compile(r'speed=\s*(\S+?)x')
_RE_FIELD = re.compile(r'(\w+)=\s*(\S+)')

FFMPEG_CMD = ["stdbuf", "-e0", "ffmpeg"]
FFMPEG_DEFAULT_ARGS = "-y -stats -hide_banner -loglevel info"


def ffmpeg_cmd_args():
    """
    Get ffmpeg command and default args
    """
    return {"ffmpeg_cmd": FFMPEG_CMD,
            "ffmpeg-default-args": FFMPEG_DEFAULT_ARGS}


def simple_one_pass(*args, **kwa):
    """
    Command builder for one pass
    """
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

    def __init__(self, progress_queue, kwargs_list, cmd_builder=simple_one_pass):
        super().__init__(daemon=True)
        self.progress_queue = progress_queue
        self.stop_work_thread = False
        self.kwargs_list = kwargs_list
        self.nargs = len(kwargs_list)
        self.count = 0
        self.cmd_builder = cmd_builder

    def run(self):
        """
        Run the separated thread.
        """
        filedone = []
        for kwa in self.kwargs_list:
            self.count += 1
            model = self.cmd_builder(self.count, self.nargs, **kwa)

            self.progress_queue.put({
                'type': 'count',
                'message': model['count1'],
                'duration': kwa['duration'],
                'status': Status.CONTINUE,
            })

            try:
                proc1 = subprocess.Popen(model['pass1'],
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
                                        self.progress_queue.put({
                                            'type': 'output',
                                            'line': line,
                                            'duration': kwa['duration'],
                                            'status': 0,
                                        })
                    except (TypeError, BlockingIOError):
                        time.sleep(0.05)

                    if self.stop_work_thread:
                        proc1.terminate()
                        try:
                            proc1.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            proc1.kill()
                        self.progress_queue.put({
                            'type': 'output',
                            'line': Status.STOP.value,
                            'duration': kwa['duration'],
                            'status': 1,
                        })
                        time.sleep(.5)
                        self.progress_queue.put({
                            'type': 'end',
                            'filedone': None,
                        })
                        return

                if self.stop_work_thread:
                    self.progress_queue.put({
                        'type': 'end',
                        'filedone': None,
                    })
                    return

                if line_buffer:
                    self.progress_queue.put({
                        'type': 'output',
                        'line': line_buffer,
                        'duration': kwa['duration'],
                        'status': 0,
                    })

                if proc1.returncode != 0:
                    self.progress_queue.put({
                        'type': 'output',
                        'line': Status.FAILED.value,
                        'duration': kwa['duration'],
                        'status': proc1.returncode,
                    })
                    time.sleep(1)
                    continue

            except (OSError, FileNotFoundError) as err:
                self.progress_queue.put({
                    'type': 'count',
                    'message': str(err),
                    'duration': 0,
                    'status': Status.ERROR,
                })
                break

            if proc1.returncode == 0:
                filedone.append(kwa["source"])
                self.progress_queue.put({
                    'type': 'count',
                    'message': '',
                    'duration': kwa['duration'],
                    'status': Status.DONE,
                })

        time.sleep(.5)
        self.progress_queue.put({
            'type': 'end',
            'filedone': filedone,
        })

    def stop(self):
        self.stop_work_thread = True


def get_duration(input_path):
    """Get media file duration in seconds via ffprobe."""
    try:
        result = subprocess.run([
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', input_path
        ], capture_output=True, text=True, check=True)
        return float(result.stdout)
    except (subprocess.CalledProcessError, ValueError):
        return 0


class BaseConverterWindow(Gtk.Window):
    """Base class for all converter windows with shared progress UI logic."""

    def __init__(self, title, files, default_size=(500, 400), show_progress_details=True):
        super().__init__(title=title)
        self.progress_queue = queue.Queue()
        self.files = files
        self.set_default_size(*default_size)
        self._show_progress_details = show_progress_details

        self.vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.vbox.set_margin_top(12)
        self.vbox.set_margin_bottom(12)
        self.vbox.set_margin_start(12)
        self.vbox.set_margin_end(12)
        self.set_child(self.vbox)

        self.thread = None
        self.connect("destroy", self._on_destroy)

    def _setup_progress_ui(self):
        """Add progress bar and labels to the UI. Call after adding custom widgets."""
        self.progress_bar = Gtk.ProgressBar()
        self.vbox.append(self.progress_bar)

        self.label_file_count = Gtk.Label()
        self.vbox.append(self.label_file_count)

        if self._show_progress_details:
            self.label_timestamps = Gtk.Label()
            self.vbox.append(self.label_timestamps)

            self.label_ffmpeg_output = Gtk.Label()
            self.label_ffmpeg_output.set_ellipsize(Pango.EllipsizeMode.END)
            self.vbox.append(self.label_ffmpeg_output)

    def _on_destroy(self, widget):
        if self.thread and self.thread.is_alive():
            self.thread.stop()

    def _start_ffmpeg(self, kwargs_list, cmd_builder=simple_one_pass):
        """Create and start FFmpeg thread, begin polling progress queue."""
        self.thread = FFmpeg(self.progress_queue, kwargs_list, cmd_builder=cmd_builder)
        self.thread.start()
        self.add_tick_callback(self._tick_poll)

    def _tick_poll(self, widget, frame_clock):
        """Poll progress queue each frame and dispatch messages to UI update methods."""
        try:
            while not self.progress_queue.empty():
                msg = self.progress_queue.get_nowait()
                self._dispatch_message(msg)
        except queue.Empty:
            pass

        thread_alive = self.thread and self.thread.is_alive()
        if thread_alive or not self.progress_queue.empty():
            return GLib.SOURCE_CONTINUE
        return GLib.SOURCE_REMOVE

    def _dispatch_message(self, msg):
        """Route a queue message to the appropriate handler."""
        msg_type = msg.get('type')
        if msg_type == 'count':
            self.update_count(msg['message'], msg['duration'], msg['status'])
        elif msg_type == 'output':
            self.update_output(msg['line'], msg['duration'], msg['status'])
        elif msg_type == 'end':
            self.end_conversion(msg.get('filedone'))

    def update_count(self, count, duration, status):
        if status == Status.ERROR:
            self.label_file_count.set_text(_("Error: {0}").format(count))
        elif status == Status.DONE:
            self.label_file_count.set_text(_("Done!"))
            self.progress_bar.set_fraction(1)
            if self._show_progress_details:
                newlab = self.label_timestamps.get_label().split()
                if _('Processing:') in newlab:
                    newlab[1] = '100%'
                if 'ETA:' in newlab:
                    newlab[3] = '00:00:00'
                self.label_timestamps.set_label(" ".join(newlab))
        else:
            self.label_file_count.set_text(count)
            self.progress_bar.set_fraction(0)
            if self._show_progress_details:
                self.label_timestamps.set_text("")
                self.label_ffmpeg_output.set_text("")

    def update_output(self, output, duration, status):
        if not self._show_progress_details:
            return

        if status != 0:
            if output == Status.STOP.value:
                self.label_ffmpeg_output.set_text(_("Conversion stopped."))
            else:
                self.label_ffmpeg_output.set_text(_("Conversion failed."))
            return

        time_match = _RE_TIME.search(output)
        if time_match:
            pos = time_match.group(1)
            msec = time_to_integer(pos)

            if msec > duration:
                self.progress_bar.set_fraction(1)
            elif msec == 0:
                self.progress_bar.set_fraction(self.progress_bar.get_fraction())
            else:
                self.progress_bar.set_fraction(msec / duration if duration > 0 else 0)

            percentage = round((msec / duration) * 100 if duration != 0 else 100)

            ffprog = [f"{k}: {v}" for k, v in _RE_FIELD.findall(output)]

            speed_match = _RE_SPEED.search(output)
            if speed_match:
                speed_str = speed_match.group(1)
                if speed_str in ('N/A', '0') or 'N/A' in speed_str:
                    eta = "ETA: N/A"
                else:
                    try:
                        rem = (duration - msec) / float(speed_str)
                        remaining = integer_to_time(round(rem), mills=False)
                        eta = f"ETA: {remaining}"
                    except (ValueError, ZeroDivisionError):
                        eta = "ETA: N/A"
            else:
                eta = "ETA: N/A"

            self.label_timestamps.set_text(_('Processing: {0}% {1}').format(str(int(percentage)), eta))
            self.label_ffmpeg_output.set_text(' | '.join(ffprog))
        else:
            print(output, end="")

    def end_conversion(self, filedone):
        """Called when conversion finishes. Override for custom behavior."""
        pass
