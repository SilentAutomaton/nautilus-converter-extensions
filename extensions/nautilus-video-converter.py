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

_ = setup_localisation()

class VideoConverterWindow(Gtk.Window):
    VCODECS = {
        "MPEG-4": {"-c:v mpeg4": ["avi"]},
        "XVID MPEG-4": {"-c:v libxvid": ["avi"]},
        "H.264": {"-c:v libx264": ["mkv", "mp4", "avi", "m4v"]},
        "H.264 10-bit": {"-c:v libx264": ["mkv", "mp4", "avi", "m4v"]},
        "H.265": {"-c:v libx265": ["mkv", "mp4", "avi", "m4v"]},
        "H.265 10-bit": {"-c:v libx265": ["mkv", "mp4", "avi", "m4v"]},
        "AOM-AV1": {"-c:v libaom-av1": ["mkv", "webm", "mp4"]},
        "SVT-AV1": {"-c:v libsvtav1": ["mkv", "webm"]},
        "SVT-AV1 10-bit": {"-c:v libsvtav1": ["mkv", "webm"]},
        "VP9": {"-c:v libvpx-vp9": ["webm", "mkv"]},
        "Copy": {"-c:v copy": ["mkv", "mp4", "avi", "m4v", "webm", "Copy"]} 
    }

    def __init__(self, files):
        super().__init__(title=_("Video Converter"))
        self.progress_queue = queue.Queue()
        self.files = files
        self.set_default_size(500, 400)

        header = Gtk.HeaderBar()
        self.set_titlebar(header)
        header.set_show_title_buttons(True)

        self.convert_button = Gtk.Button(label=_("Convert"))
        self.convert_button.get_style_context().add_class("suggested-action")
        header.pack_start(self.convert_button)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        vbox.set_margin_top(12)
        vbox.set_margin_bottom(12)
        vbox.set_margin_start(12)
        vbox.set_margin_end(12)
        self.set_child(vbox)

        #  Format and Codec selection 
        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        vbox.append(grid)

        label_vcodec = Gtk.Label(label=_("Video Codec:"))
        label_vcodec.set_halign(Gtk.Align.START)
        grid.attach(label_vcodec, 0, 0, 1, 1)

        self.vcodec_combo = Gtk.ComboBoxText()
        for codec in self.VCODECS.keys():
            self.vcodec_combo.append_text(codec)
        self.vcodec_combo.set_active(2)  # H.264
        self.vcodec_combo.connect("changed", self.on_vcodec_changed)
        grid.attach(self.vcodec_combo, 1, 0, 1, 1)

        label_format = Gtk.Label(label=_("Container:"))
        label_format.set_halign(Gtk.Align.START)
        grid.attach(label_format, 0, 1, 1, 1)

        self.format_combo = Gtk.ComboBoxText()
        self.on_vcodec_changed(self.vcodec_combo)  # Populate initially
        grid.attach(self.format_combo, 1, 1, 1, 1)

        #  Advanced options 
        advanced_box = Gtk.Box(spacing=6)
        advanced_box.set_halign(Gtk.Align.START)
        vbox.append(advanced_box)

        label_advanced = Gtk.Label(label=_("Advanced Options"))
        advanced_box.append(label_advanced)

        self.advanced_switch = Gtk.Switch()
        self.advanced_switch.connect("notify::active", self.on_advanced_toggled)
        advanced_box.append(self.advanced_switch)

        self.advanced_frame = Gtk.Frame()
        self.advanced_frame.set_visible(False)
        vbox.append(self.advanced_frame)

        self.advanced_grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        self.advanced_grid.set_margin_top(12)
        self.advanced_grid.set_margin_bottom(12)
        self.advanced_grid.set_margin_start(12)
        self.advanced_grid.set_margin_end(12)
        self.advanced_frame.set_child(self.advanced_grid)

        # Advanced options widgets 
        # CRF
        label_crf = Gtk.Label(label=_("CRF:"))
        label_crf.set_halign(Gtk.Align.START)
        self.scale_crf = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 51, 1)
        self.scale_crf.set_value(23)
        self.scale_crf.set_draw_value(True)
        self.advanced_grid.attach(label_crf, 0, 0, 1, 1)
        self.advanced_grid.attach(self.scale_crf, 1, 0, 1, 1)

        # Preset
        label_preset = Gtk.Label(label=_("Preset:"))
        label_preset.set_halign(Gtk.Align.START)
        self.preset_combo = Gtk.ComboBoxText()
        presets = ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"]
        for preset in presets:
            self.preset_combo.append_text(preset)
        self.preset_combo.set_active(5)  # medium
        self.advanced_grid.attach(label_preset, 0, 1, 1, 1)
        self.advanced_grid.attach(self.preset_combo, 1, 1, 1, 1)

        # Pixel Format
        label_pix_fmt = Gtk.Label(label=_("Pixel Format:"))
        label_pix_fmt.set_halign(Gtk.Align.START)
        self.pix_fmt_combo = Gtk.ComboBoxText()
        pix_fmts = ["yuv420p", "yuv422p", "yuv444p", "yuvj420p", "yuvj422p", "yuvj444p"]
        for fmt in pix_fmts:
            self.pix_fmt_combo.append_text(fmt)
        self.pix_fmt_combo.set_active(0)
        self.advanced_grid.attach(label_pix_fmt, 0, 2, 1, 1)
        self.advanced_grid.attach(self.pix_fmt_combo, 1, 2, 1, 1)

        # Convert button
        self.convert_button.connect("clicked", self.on_convert_clicked)

        #  Progress bar 
        self.progress_bar = Gtk.ProgressBar()
        vbox.append(self.progress_bar)

        #  Progress labels 
        self.label_file_count = Gtk.Label()
        vbox.append(self.label_file_count)

        self.label_timestamps = Gtk.Label()
        vbox.append(self.label_timestamps)

        self.label_ffmpeg_output = Gtk.Label()
        self.label_ffmpeg_output.set_ellipsize(3) # END
        vbox.append(self.label_ffmpeg_output)

    def on_vcodec_changed(self, widget):
        vcodec_str = self.vcodec_combo.get_active_text()
        containers = list(self.VCODECS[vcodec_str].values())[0]
        self.format_combo.remove_all()
        for container in containers:
            self.format_combo.append_text(container)
        self.format_combo.set_active(0)

    def on_advanced_toggled(self, widget, _):
        self.advanced_frame.set_visible(widget.get_active())

    def on_convert_clicked(self, widget):
        vcodec_str = self.vcodec_combo.get_active_text()
        video_codec = list(self.VCODECS[vcodec_str].keys())[0]
        format = self.format_combo.get_active_text()
        self.convert_button.set_sensitive(False)

        kwargs_list = []
        for file in self.files:
            input_path = file.get_location().get_path()
            output_path = os.path.splitext(input_path)[0] + f'.{format}'

            duration = self.get_duration(input_path)

            args = [video_codec]
            if self.advanced_switch.get_active():
                crf = self.scale_crf.get_value()
                args.extend(['-crf', str(int(crf))])

                preset = self.preset_combo.get_active_text()
                args.extend(['-preset', preset])

                pix_fmt = self.pix_fmt_combo.get_active_text()
                args.extend(['-pix_fmt', pix_fmt])

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

        self.thread = FFmpeg(self, self.progress_queue, kwargs_list)
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

    def update_count(self, count, duration, end):
        if end == 'ERROR':
            self.label_file_count.set_text(_("Error: {0}").format(count))
        elif end == 'DONE':
            self.label_file_count.set_text(_("Done!"))
            self.progress_bar.set_fraction(1)
            newlab = self.label_timestamps.get_label().split()
            if 'Processing:' in newlab:
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
                self.label_ffmpeg_output.set_text(_("Conversion stopped."))
            else:
                self.label_ffmpeg_output.set_text(_("Conversion failed."))
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

            self.label_timestamps.set_text(_('Processing: {0}% {1}').format(str(int(percentage)), eta))
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


class VideoConverterExtension(GObject.GObject, Nautilus.MenuProvider):
    def __init__(self):
        GObject.GObject.__init__(self)

    def get_file_items(self, files):
        if not files:
            return []

        for file in files:
            if not file.get_mime_type().startswith('video/'):
                return []

        item = Nautilus.MenuItem(
            name='VideoConverterExtension::Convert',
            label=_('Convert to'),
            tip=_('Converts selected video(s) to a different format')
        )
        item.connect('activate', self.show_converter_window, files)

        return [item]

    def show_converter_window(self, menu, files):
        win = VideoConverterWindow(files)
        win.set_visible(True)