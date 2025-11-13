import gi
gi.require_version('Nautilus', '3.0')
gi.require_version('Gtk', '3.0')
from gi.repository import Nautilus, GObject, Gtk, GLib
import queue
import subprocess
import os
import json
import shlex
from common import (
    setup_localisation,
    FFmpeg,
    ffmpeg_cmd_args,
)


def separator_pass(*args, trans, **kwa):
    """
    Command builder for separator pass.
    """
    _ = trans
    cmd = ffmpeg_cmd_args()
    
    pass1 = cmd["ffmpeg_cmd"] + cmd["ffmpeg-default-args"].split()
    pass1.extend(['-i', kwa["source"]])
    pass1.extend(kwa["args"][0].split())
    pass1.append(kwa["destination"])

    count1 = (_("File {0}/{1}: {2}").format(args[0], args[1], kwa["task_name"]))
    stamp1 = f'{count1}\n\n[COMMAND]:\n{" ".join(shlex.quote(arg) for arg in pass1)}'

    return {'pass1': pass1, 'count1': count1, 'stamp1': stamp1}


class SeparatorWindow(Gtk.Window):
    def __init__(self, files, trans):
        self._ = trans
        super().__init__(title=self._("Separating Audio/Video"))
        self.progress_queue = queue.Queue()
        self.files = files
        self.set_default_size(400, 100)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        vbox.set_margin_top(12)
        vbox.set_margin_bottom(12)
        vbox.set_margin_left(12)
        vbox.set_margin_right(12)
        self.add(vbox)

        self.label_file_count = Gtk.Label()
        vbox.pack_start(self.label_file_count, True, True, 0)

        self.cancel_button = Gtk.Button(label=self._("Cancel"))
        self.cancel_handler_id = self.cancel_button.connect("clicked", self.on_cancel_clicked)
        vbox.pack_start(self.cancel_button, True, True, 0)

        self.start_separation()

    def on_cancel_clicked(self, widget):
        if hasattr(self, 'thread') and self.thread.is_alive():
            self.thread.stop()
        self.cancel_button.set_sensitive(False)

    def get_stream_info(self, input_path):
        try:
            probe_process = subprocess.run([
                'ffprobe', '-v', 'error', '-show_streams', '-print_format', 'json', input_path
            ], capture_output=True, text=True, check=True)
            return json.loads(probe_process.stdout)['streams']
        except (subprocess.CalledProcessError, ValueError, KeyError):
            return []

    def get_duration(self, input_path):
        try:
            duration_process = subprocess.run([
                'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1', input_path
            ], capture_output=True, text=True, check=True)
            return float(duration_process.stdout)
        except (subprocess.CalledProcessError, ValueError):
            return 0

    def start_separation(self):
        tasks = []
        for file in self.files:
            input_path = file.get_location().get_path()
            base_path, ext = os.path.splitext(input_path)
            duration = self.get_duration(input_path)

            streams = self.get_stream_info(input_path)
            audio_streams = [s for s in streams if s['codec_type'] == 'audio']

            # Video task
            video_output_path = f"{base_path}_video{ext}"
            video_args = ['-vcodec', 'copy', '-an']
            tasks.append({
                'source': input_path,
                'destination': video_output_path,
                'duration': duration * 1000,
                'args': [' '.join(video_args), None],
                'task_name': self._("Separating video track"),
                'start-time': '',
                'end-time': '',
            })

            # Audio tasks
            for i, audio_stream in enumerate(audio_streams):
                audio_index = audio_stream['index']
                try:
                    audio_format = subprocess.run([
                        'ffprobe', '-v', 'error', '-select_streams', f'a:{i}', '-show_entries', 'stream=codec_name',
                        '-of', 'default=noprint_wrappers=1:nokey=1', input_path
                    ], capture_output=True, text=True, check=True).stdout.strip()
                except (subprocess.CalledProcessError, ValueError):
                    audio_format = 'aac' # fallback
                
                audio_output_path = f"{base_path}_audio_{i}.{audio_format}"
                audio_args = ['-map', f'0:{audio_index}', '-acodec', 'copy']
                tasks.append({
                    'source': input_path,
                    'destination': audio_output_path,
                    'duration': duration * 1000,
                    'args': [' '.join(audio_args), None],
                    'task_name': self._("Separating audio track {0}").format(i + 1),
                    'start-time': '',
                    'end-time': '',
                })
        
        if not tasks:
            self.update_count(self._("Error: No streams found to separate."), 0, 'ERROR')
            GLib.timeout_add(2000, self.close)
            return

        self.thread = FFmpeg(self, self.progress_queue, tasks, cmd_builder=separator_pass, trans=self._)
        GLib.timeout_add(100, self.update_progress_from_queue)

    def update_count(self, count, duration, end):
        if end == 'ERROR':
            self.label_file_count.set_text(self._("Error: {0}").format(count))
        elif end == 'DONE':
            self.label_file_count.set_text(self._("Done!"))
        else:
            self.label_file_count.set_text(count)

    def update_output(self, output, duration, status):
        # This is now a no-op, but needs to exist for FFmpeg class callbacks.
        pass

    def end_conversion(self, filedone):
        self.cancel_button.set_label(self._("Close"))
        self.cancel_button.set_sensitive(True)
        if self.cancel_handler_id > 0:
            self.cancel_button.disconnect(self.cancel_handler_id)
            self.cancel_handler_id = 0
        GLib.timeout_add(1000, self.close)

    def update_progress_from_queue(self):
        try:
            while not self.progress_queue.empty():
                self.progress_queue.get_nowait()
        except queue.Empty:
            pass

        if hasattr(self, 'thread') and self.thread.is_alive():
            return True # Keep timer running
        else:
            # One final drain of the queue
            try:
                while not self.progress_queue.empty():
                    self.progress_queue.get_nowait()
            except queue.Empty:
                pass
            return False # Stop timer


class VideoAudioSeparatorExtension(GObject.GObject, Nautilus.MenuProvider):
    def __init__(self):
        GObject.GObject.__init__(self)
        self._ = setup_localisation()

    def get_file_items(self, window, files):
        self._ = setup_localisation()
        if not files:
            return []

        for file in files:
            if not file.get_mime_type().startswith('video/'):
                return []

        item = Nautilus.MenuItem(
            name='VideoAudioSeparatorExtension::Separate',
            label=self._('Separate Audio/Video'),
            tip=self._('Separates audio and video from selected video file(s)')
        )
        item.connect('activate', self.show_separator_window, files)

        return [item]

    def show_separator_window(self, menu, files):
        win = SeparatorWindow(files, self._)
        win.show_all()
