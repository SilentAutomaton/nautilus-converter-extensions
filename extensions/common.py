import subprocess
import codecs
import os
import re
import gettext
import locale
import threading
import select
import time
import queue
import traceback
from enum import Enum

import gi
gi.require_version('Gtk', '4.0')
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


def simple_one_pass(*args, **kwa):
    pass1 = (FFMPEG_CMD +
             FFMPEG_DEFAULT_ARGS.split() +
             ["-i", kwa["source"]] +
             kwa["args"][0].split() +
             [kwa["destination"]])

    count1 = (_("File {0}/{1}\nSource: \"{2}\"\nDestination: \"{3}\" ").format(args[0], args[1], kwa["source"], kwa["destination"]))

    return {'pass1': pass1, 'count1': count1}


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
                              stdin=subprocess.DEVNULL,
                              bufsize=0)

                fd = proc1.stderr.fileno()
                decoder = codecs.getincrementaldecoder('utf-8')('replace')
                line_buffer = ""
                # Read to EOF, not until the process exits: ffmpeg emits its
                # stats in a final burst, which a poll()-bound loop never reads.
                while True:
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

                    if not select.select([fd], [], [], 0.1)[0]:
                        continue

                    chunk = os.read(fd, 65536)
                    if not chunk:
                        break

                    line_buffer += decoder.decode(chunk)
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

                proc1.wait()

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
        while not self.progress_queue.empty():
            try:
                self._dispatch_message(self.progress_queue.get_nowait())
            except queue.Empty:
                break
            except Exception:
                traceback.print_exc()

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
                self.label_timestamps.set_text(
                    _('Processing: {0}% {1}').format('100', 'ETA: 00:00:00'))
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

            fraction = min(msec / duration, 1.0) if duration > 0 else 1.0
            if msec > 0:
                self.progress_bar.set_fraction(fraction)

            percentage = round(fraction * 100)

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

    def end_conversion(self, filedone):
        """Called when conversion finishes. Override for custom behavior."""
        pass
