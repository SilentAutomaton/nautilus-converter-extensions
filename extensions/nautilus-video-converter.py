from gi.repository import Nautilus, GObject, Gtk
import subprocess
import os
from common import (
    setup_localisation,
    get_duration,
    BaseConverterWindow,
)

_ = setup_localisation()


class VideoConverterWindow(BaseConverterWindow):
    VCODECS = {
        "MPEG-4": {"-c:v mpeg4": ["avi"]},
        "XVID MPEG-4": {"-c:v libxvid": ["avi"]},
        "H.264": {"-c:v libx264": ["mkv", "mp4", "avi", "m4v"]},
        "H.264 10-bit": {"-c:v libx264 -pix_fmt yuv420p10le": ["mkv", "mp4", "avi", "m4v"]},
        "H.265": {"-c:v libx265": ["mkv", "mp4", "avi", "m4v"]},
        "H.265 10-bit": {"-c:v libx265 -pix_fmt yuv420p10le": ["mkv", "mp4", "avi", "m4v"]},
        "AOM-AV1": {"-c:v libaom-av1": ["mkv", "webm", "mp4"]},
        "SVT-AV1": {"-c:v libsvtav1": ["mkv", "webm"]},
        "SVT-AV1 10-bit": {"-c:v libsvtav1 -pix_fmt yuv420p10le": ["mkv", "webm"]},
        "VP9": {"-c:v libvpx-vp9": ["webm", "mkv"]},
        "Copy": {"-c:v copy": ["mkv", "mp4", "avi", "m4v", "webm"]}
    }

    # Codecs that pin their own pixel format; the advanced dropdown must not override it.
    TEN_BIT = frozenset(["H.264 10-bit", "H.265 10-bit", "SVT-AV1 10-bit"])

    def __init__(self, files):
        super().__init__(title=_("Video Converter"), files=files)

        header = Gtk.HeaderBar()
        self.set_titlebar(header)
        header.set_show_title_buttons(True)

        self.convert_button = Gtk.Button(label=_("Convert"))
        self.convert_button.get_style_context().add_class("suggested-action")
        header.pack_start(self.convert_button)

        #  Format and Codec selection
        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        self.vbox.append(grid)

        label_vcodec = Gtk.Label(label=_("Video Codec:"))
        label_vcodec.set_halign(Gtk.Align.START)
        grid.attach(label_vcodec, 0, 0, 1, 1)

        self.vcodec_combo = Gtk.ComboBoxText()
        for codec in self.VCODECS.keys():
            self.vcodec_combo.append_text(codec)
        self.vcodec_combo.set_active(2)  # H.264
        self.vcodec_combo.connect("changed", self.on_vcodec_changed)
        grid.attach(self.vcodec_combo, 1, 0, 1, 1)

        label_container = Gtk.Label(label=_("Container:"))
        label_container.set_halign(Gtk.Align.START)
        grid.attach(label_container, 0, 1, 1, 1)

        self.container_combo = Gtk.ComboBoxText()
        self.on_vcodec_changed(self.vcodec_combo)  # Populate initially
        grid.attach(self.container_combo, 1, 1, 1, 1)

        #  Advanced options
        advanced_box = Gtk.Box(spacing=6)
        advanced_box.set_halign(Gtk.Align.START)
        self.vbox.append(advanced_box)

        label_advanced = Gtk.Label(label=_("Advanced Options"))
        advanced_box.append(label_advanced)

        self.advanced_switch = Gtk.Switch()
        self.advanced_switch.connect("notify::active", self.on_advanced_toggled)
        advanced_box.append(self.advanced_switch)

        self.advanced_frame = Gtk.Frame()
        self.advanced_frame.set_visible(False)
        self.vbox.append(self.advanced_frame)

        self.advanced_grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        self.advanced_grid.set_margin_top(12)
        self.advanced_grid.set_margin_bottom(12)
        self.advanced_grid.set_margin_start(12)
        self.advanced_grid.set_margin_end(12)
        self.advanced_frame.set_child(self.advanced_grid)

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

        # Resolution
        label_resolution = Gtk.Label(label=_("Resolution:"))
        label_resolution.set_halign(Gtk.Align.START)
        self.entry_width = Gtk.Entry()
        self.entry_height = Gtk.Entry()
        self.check_keep_aspect = Gtk.CheckButton(label=_("Keep Aspect Ratio"))
        self.check_keep_aspect.set_active(True)

        resolution_box = Gtk.Box(spacing=6)
        resolution_box.append(self.entry_width)
        resolution_box.append(Gtk.Label(label="x"))
        resolution_box.append(self.entry_height)
        resolution_box.append(self.check_keep_aspect)

        self.advanced_grid.attach(label_resolution, 0, 3, 1, 1)
        self.advanced_grid.attach(resolution_box, 1, 3, 1, 1)

        # Bitrate
        label_bitrate = Gtk.Label(label=_("Bitrate (kbps):"))
        label_bitrate.set_halign(Gtk.Align.START)
        self.entry_bitrate = Gtk.Entry()
        self.advanced_grid.attach(label_bitrate, 0, 4, 1, 1)
        self.advanced_grid.attach(self.entry_bitrate, 1, 4, 1, 1)

        # Convert button
        self.convert_button.connect("clicked", self.on_convert_clicked)

        # Progress UI from base class
        self._setup_progress_ui()

        video_infos = []
        for file in self.files:
            video_infos.append(self.get_video_info(file.get_location().get_path()))

        all_same_resolution = len(set((info[0], info[1]) for info in video_infos)) == 1
        all_same_pix_fmt = len(set(info[2] for info in video_infos)) == 1
        all_same_bitrate = len(set(info[3] for info in video_infos)) == 1

        if video_infos and all(info[0] is not None for info in video_infos):
            self.original_width, self.original_height, pix_fmt, bitrate = video_infos[0]

            if all_same_resolution:
                self.entry_width.set_text(str(self.original_width))
                self.entry_height.set_text(str(self.original_height))
                self.entry_width.connect("changed", self.on_width_changed)
                self.entry_height.connect("changed", self.on_height_changed)
            else:
                self.entry_width.set_sensitive(False)
                self.entry_height.set_sensitive(False)
                self.check_keep_aspect.set_sensitive(False)

            if all_same_pix_fmt:
                for i, item in enumerate(self.pix_fmt_combo.get_model()):
                    if item[0] == pix_fmt:
                        self.pix_fmt_combo.set_active(i)
                        break
            else:
                self.pix_fmt_combo.set_sensitive(False)

            if all_same_bitrate:
                self.entry_bitrate.set_text(str(bitrate // 1000) if bitrate else "")
            else:
                self.entry_bitrate.set_sensitive(False)
        else:
            self.entry_width.set_sensitive(False)
            self.entry_height.set_sensitive(False)
            self.check_keep_aspect.set_sensitive(False)
            self.pix_fmt_combo.set_sensitive(False)
            self.entry_bitrate.set_sensitive(False)

    def on_vcodec_changed(self, widget):
        vcodec_str = self.vcodec_combo.get_active_text()
        containers = list(self.VCODECS[vcodec_str].values())[0]
        self.container_combo.remove_all()
        for container in containers:
            self.container_combo.append_text(container)
        self.container_combo.set_active(0)

    def on_advanced_toggled(self, widget, _):
        self.advanced_frame.set_visible(widget.get_active())

    def on_convert_clicked(self, widget):
        vcodec_str = self.vcodec_combo.get_active_text()
        video_codec = list(self.VCODECS[vcodec_str].keys())[0]
        container = self.container_combo.get_active_text()
        self.convert_button.set_sensitive(False)

        kwargs_list = []
        for file in self.files:
            input_path = file.get_location().get_path()
            base, ext = os.path.splitext(input_path)
            if ext.lstrip('.').lower() == container.lower():
                output_path = f'{base}_converted.{container}'
            else:
                output_path = f'{base}.{container}'

            duration = get_duration(input_path)

            args = [video_codec]
            if self.advanced_switch.get_active():
                crf = self.scale_crf.get_value()
                args.extend(['-crf', str(int(crf))])

                preset = self.preset_combo.get_active_text()
                args.extend(['-preset', preset])

                pix_fmt = self.pix_fmt_combo.get_active_text()
                if vcodec_str not in self.TEN_BIT:
                    args.extend(['-pix_fmt', pix_fmt])

                if len(self.files) == 1:
                    width = self.entry_width.get_text()
                    height = self.entry_height.get_text()
                    if width and height and width.isdigit() and height.isdigit():
                        i_width = int(width)
                        i_height = int(height)
                        pix_fmt = self.pix_fmt_combo.get_active_text()
                        if 'yuv420p' in pix_fmt:
                            i_width = round(i_width / 2) * 2
                            i_height = round(i_height / 2) * 2
                        args.extend(['-vf', f'scale={i_width}:{i_height}'])

                    bitrate = self.entry_bitrate.get_text()
                    if bitrate and bitrate.isdigit():
                        args.extend(['-b:v', f'{bitrate}k'])

            kwargs = {
                'source': input_path,
                'destination': output_path,
                'args': [' '.join(args)],
                'duration': duration * 1000,
            }
            kwargs_list.append(kwargs)

        self._start_ffmpeg(kwargs_list)

    def get_video_info(self, input_path):
        try:
            info_process = subprocess.run([
                'ffprobe', '-v', 'error', '-select_streams', 'v:0',
                '-show_entries', 'stream=width,height,pix_fmt,bit_rate', '-of',
                'default=noprint_wrappers=1:nokey=1', input_path
            ], capture_output=True, text=True, check=True)
            width, height, pix_fmt, bit_rate = info_process.stdout.strip().split('\n')
            return int(width), int(height), pix_fmt, int(bit_rate) if bit_rate.isdigit() else 0
        except (subprocess.CalledProcessError, ValueError):
            return None, None, None, None

    def on_width_changed(self, widget):
        if self.check_keep_aspect.get_active() and self.original_width and self.original_height:
            try:
                new_width = int(self.entry_width.get_text())
                if new_width > 0:
                    new_height = int(new_width * self.original_height / self.original_width)
                    self.entry_height.handler_block_by_func(self.on_height_changed)
                    self.entry_height.set_text(str(new_height))
                    self.entry_height.handler_unblock_by_func(self.on_height_changed)
            except ValueError:
                pass

    def on_height_changed(self, widget):
        if self.check_keep_aspect.get_active() and self.original_width and self.original_height:
            try:
                new_height = int(self.entry_height.get_text())
                if new_height > 0:
                    new_width = int(new_height * self.original_width / self.original_height)
                    self.entry_width.handler_block_by_func(self.on_width_changed)
                    self.entry_width.set_text(str(new_width))
                    self.entry_width.handler_unblock_by_func(self.on_width_changed)
            except ValueError:
                pass

    def end_conversion(self, filedone):
        self.convert_button.set_sensitive(True)


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
