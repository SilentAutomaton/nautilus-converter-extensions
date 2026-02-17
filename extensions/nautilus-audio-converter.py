from gi.repository import Nautilus, GObject, Gtk
import os
from common import (
    setup_localisation,
    get_duration,
    BaseConverterWindow,
)

_ = setup_localisation()


class AudioConverterWindow(BaseConverterWindow):
    ACODECS = {
        "MP3": {"-c:a libmp3lame": ["mp3"]},
        "OGG": {"-c:a libvorbis": ["ogg"]},
        "WAV": {"-c:a pcm_s16le": ["wav"]},
        "FLAC": {"-c:a flac": ["flac"]},
        "Copy": {"-c:a copy": ["mka", "mp3", "ogg", "wav", "flac"]}
    }

    def __init__(self, files):
        super().__init__(title=_("Audio Converter"), files=files)

        header = Gtk.HeaderBar()
        self.set_titlebar(header)
        header.set_show_title_buttons(True)

        self.convert_button = Gtk.Button(label=_("Convert"))
        self.convert_button.get_style_context().add_class("suggested-action")
        header.pack_start(self.convert_button)

        #  Format and Codec selection
        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        self.vbox.append(grid)

        label_acodec = Gtk.Label(label=_("Audio Codec:"))
        label_acodec.set_halign(Gtk.Align.START)
        grid.attach(label_acodec, 0, 0, 1, 1)

        self.acodec_combo = Gtk.ComboBoxText()
        for codec in self.ACODECS.keys():
            self.acodec_combo.append_text(codec)
        self.acodec_combo.set_active(0)  # MP3
        grid.attach(self.acodec_combo, 1, 0, 1, 1)

        # Convert button
        self.convert_button.connect("clicked", self.on_convert_clicked)

        # Progress UI from base class
        self._setup_progress_ui()

    def on_convert_clicked(self, widget):
        acodec_str = self.acodec_combo.get_active_text()
        audio_codec = list(self.ACODECS[acodec_str].keys())[0]
        container = self.ACODECS[acodec_str][audio_codec][0]
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

            args = [audio_codec]

            kwargs = {
                'type': 'One pass',
                'source': input_path,
                'destination': output_path,
                'start-time': '',
                'end-time': '',
                'args': [' '.join(args), None],
                'duration': duration * 1000,
            }
            kwargs_list.append(kwargs)

        self._start_ffmpeg(kwargs_list)

    def end_conversion(self, filedone):
        self.convert_button.set_sensitive(True)


class AudioConverterExtension(GObject.GObject, Nautilus.MenuProvider):
    def __init__(self):
        GObject.GObject.__init__(self)

    def get_file_items(self, files):
        if not files:
            return []

        for file in files:
            if not file.get_mime_type().startswith('audio/'):
                return []

        item = Nautilus.MenuItem(
            name='AudioConverterExtension::Convert',
            label=_('Convert to'),
            tip=_('Converts selected audio(s) to a different format')
        )
        item.connect('activate', self.show_converter_window, files)

        return [item]

    def show_converter_window(self, menu, files):
        win = AudioConverterWindow(files)
        win.set_visible(True)
