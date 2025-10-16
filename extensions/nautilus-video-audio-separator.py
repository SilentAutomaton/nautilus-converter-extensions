from gi.repository import Nautilus, GObject, Gtk, GLib
import fcntl, queue, time
import subprocess
import os
import threading
from common import setup_localisation, Popen, time_to_integer

_ = setup_localisation()

class SeparatorWindow(Gtk.Window):
    def __init__(self, files):
        super().__init__(title=_("Separating Audio/Video"))
        self.progress_queue = queue.Queue()
        self.files = files
        self.set_default_size(400, 100)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        vbox.set_margin_top(12)
        vbox.set_margin_bottom(12)
        vbox.set_margin_start(12)
        vbox.set_margin_end(12)
        self.set_child(vbox)

        self.label = Gtk.Label(label=_("Separating audio and video for selected files..."))
        vbox.append(self.label)

        self.progress_bar = Gtk.ProgressBar()
        vbox.append(self.progress_bar)

        self.thread = threading.Thread(target=self.separate_files_thread)
        self.thread.start()
        GLib.timeout_add(2000, self.update_progress_from_queue)

    def get_duration(self, input_path):
        try:
            duration_process = subprocess.run([
                'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1', input_path
            ], capture_output=True, text=True, check=True)
            return float(duration_process.stdout)
        except (subprocess.CalledProcessError, ValueError):
            return 0

    def run_ffmpeg_process(self, cmd, duration):
        try:
            proc = Popen(cmd, stderr=subprocess.PIPE, stdin=subprocess.PIPE, encoding='utf-8', universal_newlines=True)

            fd = proc.stderr.fileno()
            fl = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

            line_buffer = ""
            while proc.poll() is None:
                try:
                    data = proc.stderr.read()
                    if data:
                        line_buffer += data
                        if '\r' in line_buffer or '\n' in line_buffer:
                            lines = line_buffer.replace('\r', '\n').split('\n')
                            line_buffer = lines.pop()
                            for line in lines:
                                if line:
                                    self.progress_queue.put({'line': line, 'duration': duration, 'status': 0})
                except (TypeError, BlockingIOError):
                    time.sleep(0.05)
            
            if proc.returncode != 0:
                # Handle error
                pass

        except (OSError, FileNotFoundError) as e:
            GLib.idle_add(self.update_ui_on_error, str(e))

    def separate_files_thread(self):
        for i, file in enumerate(self.files):
            input_path = file.get_location().get_path()
            base_path, _ = os.path.splitext(input_path)
            video_format = os.path.splitext(input_path)[1][1:]
            duration = self.get_duration(input_path) * 1000 # milliseconds

            try:
                audio_format_process = subprocess.run([
                    'ffprobe', '-v', 'error', '-select_streams', 'a:0', '-show_entries', 'stream=codec_name',
                    '-of', 'default=noprint_wrappers=1:nokey=1', input_path
                ], capture_output=True, text=True, check=True)
                audio_format = audio_format_process.stdout.strip()

            except (subprocess.CalledProcessError, ValueError):
                GLib.idle_add(self.update_ui_on_error, _("Failed to get stream information."))
                return

            video_output_path = f"{base_path}_video.{video_format}"
            audio_output_path = f"{base_path}_audio.{audio_format}"

            # Separate video
            self.run_ffmpeg_process(['ffmpeg', '-i', input_path, '-vcodec', 'copy', '-an', '-y', video_output_path], duration)
            
            # Separate audio
            self.run_ffmpeg_process(['ffmpeg', '-i', input_path, '-acodec', 'copy', '-vn', '-y', audio_output_path], duration)

            fraction = (i + 1) / len(self.files)
            GLib.idle_add(self.progress_bar.set_fraction, fraction)

        GLib.idle_add(self.close)

    def update_ui_on_error(self, error_message):
        self.label.set_text(_("Error: {0}").format(error_message))

    def update_output(self, output, duration, status):
        if 'time=' in output:
            i = output.index('time=') + 5
            pos = output[i:].split()[0]
            msec = time_to_integer(pos)

            if msec > duration:
                self.progress_bar.set_fraction(1)
            elif msec > 0:
                self.progress_bar.set_fraction(msec / duration if duration > 0 else 0)

    def update_progress_from_queue(self):
        try:
            while not self.progress_queue.empty():
                progress_info = self.progress_queue.get_nowait()
                self.update_output(
                    progress_info['line'],
                    progress_info['duration'],
                    progress_info['status']
                )
        except queue.Empty:
            pass

        if self.thread.is_alive():
            return True # Keep timer running
        else:
            return False # Stop timer

class VideoAudioSeparatorExtension(GObject.GObject, Nautilus.MenuProvider):
    def __init__(self):
        GObject.GObject.__init__(self)

    def get_file_items(self, files):
        if not files:
            return []

        for file in files:
            if not file.get_mime_type().startswith('video/'):
                return []

        item = Nautilus.MenuItem(
            name='VideoAudioSeparatorExtension::Separate',
            label=_('Separate Audio/Video'),
            tip=_('Separates audio and video from selected video file(s)')
        )
        item.connect('activate', self.show_separator_window, files)

        return [item]

    def show_separator_window(self, menu, files):
        win = SeparatorWindow(files)
        win.set_visible(True)