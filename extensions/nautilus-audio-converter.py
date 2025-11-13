import gi
gi.require_version('Nautilus', '3.0')
gi.require_version('Gtk', '3.0')
from gi.repository import Nautilus, GObject, Gtk, GLib
import queue
import subprocess
import os
from common import (
    setup_localisation,
    time_to_integer,
    integer_to_time,
    pairwise,
    FFmpeg
)

class AudioConverterWindow(Gtk.Window):
    ACODECS = {
        "MP3": {"-c:a libmp3lame": ["mp3"]},
        "OGG": {"-c:a libvorbis": ["ogg"]},
        "WAV": {"-c:a pcm_s16le": ["wav"]},
        "FLAC": {"-c:a flac": ["flac"]},
        "Copy": {"-c:a copy": ["mka", "mp3", "ogg", "wav", "flac"]} 
    }

    def __init__(self, files, trans):
        self._ = trans
        super().__init__(title=self._("Audio Converter"))
        self.progress_queue = queue.Queue()
        self.files = files
        self.set_default_size(500, 400)

        header = Gtk.HeaderBar()
        self.set_titlebar(header)
        header.set_show_close_button(True)

        self.convert_button = Gtk.Button(label=self._("Convert"))
        self.convert_button.get_style_context().add_class("suggested-action")
        header.pack_start(self.convert_button)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        vbox.set_margin_top(12)
        vbox.set_margin_bottom(12)
        vbox.set_margin_left(12)
        vbox.set_margin_right(12)
        self.add(vbox)

        #  Format and Codec selection 
        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        vbox.pack_start(grid, False, False, 0)

        label_acodec = Gtk.Label(label=self._("Audio Codec:"))
        label_acodec.set_halign(Gtk.Align.START)
        grid.attach(label_acodec, 0, 0, 1, 1)

        self.acodec_combo = Gtk.ComboBoxText()
        for codec in self.ACODECS.keys():
            self.acodec_combo.append_text(codec)
        self.acodec_combo.set_active(0)  # MP3
        grid.attach(self.acodec_combo, 1, 0, 1, 1)

        # Convert button
        self.convert_button.connect("clicked", self.on_convert_clicked)

        #  Progress bar 
        self.progress_bar = Gtk.ProgressBar()
        vbox.pack_start(self.progress_bar, False, False, 0)

        #  Progress labels 
        self.label_file_count = Gtk.Label()
        vbox.pack_start(self.label_file_count, False, False, 0)

        self.label_timestamps = Gtk.Label()
        vbox.pack_start(self.label_timestamps, False, False, 0)

        self.label_ffmpeg_output = Gtk.Label()
        self.label_ffmpeg_output.set_ellipsize(3) # END
        vbox.pack_start(self.label_ffmpeg_output, False, False, 0)

        self.connect("destroy", self.on_destroy)

    def on_destroy(self, widget):
        if hasattr(self, 'thread') and self.thread.is_alive():
            self.thread.stop()

    def on_convert_clicked(self, widget):
        acodec_str = self.acodec_combo.get_active_text()
        audio_codec = list(self.ACODECS[acodec_str].keys())[0]
        format = self.ACODECS[acodec_str][audio_codec][0]
        self.convert_button.set_sensitive(False)

        kwargs_list = []
        for file in self.files:
            input_path = file.get_location().get_path()
            output_path = os.path.splitext(input_path)[0] + f'.{format}'

            duration = self.get_duration(input_path)

            args = [audio_codec]

            kwargs = {
                'type': 'One pass',
                'source': input_path,
                'destination': output_path,
                'start-time': '',
                'end-time': '',
                'args': [' '.join(args), None],
                'duration': duration * 1000,  # Convert to milliseconds
            }
            kwargs_list.append(kwargs)

        self.thread = FFmpeg(self, self.progress_queue, kwargs_list, trans=self._)
        GLib.timeout_add(100, self.update_progress_from_queue)

    def get_duration(self, input_path):
        try:
            duration_process = subprocess.run([
                'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1', input_path
            ], capture_output=True, text=True, check=True)
            return float(duration_process.stdout)
        except (subprocess.CalledProcessError, ValueError):
            return 0

    def update_count(self, count, duration, end):
        if end == 'ERROR':
            self.label_file_count.set_text(self._("Error: {0}").format(count))
        elif end == 'DONE':
            self.label_file_count.set_text(self._("Done!"))
            self.progress_bar.set_fraction(1)
            newlab = self.label_timestamps.get_label().split()
            if self._('Processing:') in newlab:
                newlab[1] = '100%'
            if 'ETA:' in newlab:
                newlab[3] = '00:00:00'
            self.label_timestamps.set_label(" ".join(newlab))
        else:
            self.label_file_count.set_text(count)
            self.progress_bar.set_fraction(0)
            self.label_timestamps.set_text("")
            self.label_ffmpeg_output.set_text("")

    def update_output(self, output, duration, status):
        if status != 0:
            if output == 'STOP':
                self.label_ffmpeg_output.set_text(self._("Conversion stopped."))
            else:
                self.label_ffmpeg_output.set_text(self._("Conversion failed."))
            return

        if 'time=' in output:
            i = output.index('time=') + 5
            pos = output[i:].split()[0]
            msec = time_to_integer(pos)

            if msec > duration:
                self.progress_bar.set_fraction(1)
            elif msec == 0:
                self.progress_bar.set_fraction(self.progress_bar.get_fraction())
            else:
                self.progress_bar.set_fraction(msec / duration if duration > 0 else 0)

            percentage = round((msec / duration) * 100 if duration != 0 else 100)
            out = [a for a in "=".join(output.split()).split('=') if a]
            ffprog = []
            for key, val in pairwise(out):
                ffprog.append(f"{key}: {val}")

            if 'speed=' in output:
                speed = output.split('speed=')[-1].strip().split('x')[0]
                if speed in ('N/A', '0') or 'N/A' in speed:
                    eta = "ETA: N/A"
                else:
                    try:
                        rem = (duration - msec) / float(speed)
                        remaining = integer_to_time(round(rem), mills=False)
                        eta = f"ETA: {remaining}"
                    except (ValueError, ZeroDivisionError):
                        eta = "ETA: N/A"
            else:
                eta = "ETA: N/A"

            self.label_timestamps.set_text(self._('Processing: {0}% {1}').format(str(int(percentage)), eta))
            self.label_ffmpeg_output.set_text(' | '.join(ffprog))
        else:
            print(output, end="")

    def end_conversion(self, filedone):
        self.convert_button.set_sensitive(True)
        # self.destroy()

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

        if hasattr(self, 'thread') and self.thread.is_alive():
            return True # Keep timer running
        else:
            # One final drain of the queue
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
            return False # Stop timer

class AudioConverterExtension(GObject.GObject, Nautilus.MenuProvider):
    def __init__(self):
        GObject.GObject.__init__(self)
        self._ = setup_localisation()

    def get_file_items(self, window, files):
        self._ = setup_localisation()
        if not files:
            return []

        for file in files:
            if not file.get_mime_type().startswith('audio/'):
                return []

        item = Nautilus.MenuItem(
            name='AudioConverterExtension::Convert',
            label=self._('Convert to'),
            tip=self._('Converts selected audio(s) to a different format')
        )
        item.connect('activate', self.show_converter_window, files)

        return [item]

    def show_converter_window(self, menu, files):
        win = AudioConverterWindow(files, self._)
        win.show_all()
