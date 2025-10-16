from gi.repository import Nautilus, GObject, Gtk, GLib
import fcntl, queue, time
import subprocess
import os
import threading
from common import setup_localisation, Popen, time_to_integer

_ = setup_localisation()

class CombinerWindow(Gtk.Window):
    def __init__(self, files):
        super().__init__(title=_("Combining Audio/Video"))
        self.progress_queue = queue.Queue()
        self.files = files
        self.set_default_size(400, 100)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        vbox.set_margin_top(12)
        vbox.set_margin_bottom(12)
        vbox.set_margin_start(12)
        vbox.set_margin_end(12)
        self.set_child(vbox)

        self.label = Gtk.Label(label=_("Combining audio and video..."))
        vbox.append(self.label)

        self.progress_bar = Gtk.ProgressBar()
        vbox.append(self.progress_bar)

        self.thread = threading.Thread(target=self.combine_files_thread)
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

    def combine_files_thread(self):
        video_file = None
        audio_file = None

        for file in self.files:
            if file.get_mime_type().startswith('video/'):
                video_file = file.get_location().get_path()
            elif file.get_mime_type().startswith('audio/'):
                audio_file = file.get_location().get_path()

        if not video_file or not audio_file:
            GLib.idle_add(self.update_ui_on_error, _("Please select one video and one audio file."))
            return

        duration = self.get_duration(video_file) * 1000 # milliseconds
        video_format = os.path.splitext(video_file)[1][1:]
        output_path = os.path.splitext(video_file)[0] + f"_combined.{video_format}"

        try:
            cmd = ['ffmpeg', '-i', video_file, '-i', audio_file, '-c:v', 'copy', '-c:a', 'aac', '-y', output_path]
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
            return

        GLib.idle_add(self.progress_bar.set_fraction, 1.0)

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
            self.close()
            return False # Stop timer

class VideoAudioCombinerExtension(GObject.GObject, Nautilus.MenuProvider):
    def __init__(self):
        GObject.GObject.__init__(self)

    def get_file_items(self, files):
        if len(files) != 2:
            return []

        video_file_selected = False
        audio_file_selected = False

        for file in files:
            if file.get_mime_type().startswith('video/'):
                video_file_selected = True
            elif file.get_mime_type().startswith('audio/'):
                audio_file_selected = True

        if not (video_file_selected and audio_file_selected):
            return []

        item = Nautilus.MenuItem(
            name='VideoAudioCombinerExtension::Combine',
            label=_('Combine Audio/Video'),
            tip=_('Combines a video file and an audio file')
        )
        item.connect('activate', self.show_combiner_window, files)

        return [item]

    def show_combiner_window(self, menu, files):
        win = CombinerWindow(files)
        win.set_visible(True)