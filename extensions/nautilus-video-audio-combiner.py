from gi.repository import Nautilus, GObject, Gtk, GLib
import os
import shlex
from common import (
    setup_localisation,
    get_duration,
    ffmpeg_cmd_args,
    BaseConverterWindow,
)

_ = setup_localisation()


def combiner_pass(*args, **kwa):
    """
    Command builder for combiner pass.
    """
    cmd = ffmpeg_cmd_args()

    pass1 = cmd["ffmpeg_cmd"] + cmd["ffmpeg-default-args"].split()
    pass1.extend(['-i', kwa["video_file"]])
    for audio_file in kwa["audio_files"]:
        pass1.extend(['-i', audio_file])

    pass1.extend(['-map', '0'])
    for i in range(len(kwa["audio_files"])):
        pass1.extend(['-map', f'{i+1}:a'])

    pass1.extend(['-c', 'copy', kwa["destination"]])

    count1 = (_("Combining video \"{0}\" with {1} audio file(s) ...").format(kwa["video_file"], len(kwa["audio_files"])))
    stamp1 = f'{count1}\n\n[COMMAND]:\n' + " ".join(shlex.quote(arg) for arg in pass1)

    return {'pass1': pass1, 'count1': count1, 'stamp1': stamp1}


class CombinerWindow(BaseConverterWindow):
    def __init__(self, files):
        super().__init__(
            title=_("Combining Audio/Video"),
            files=files,
            default_size=(400, 100),
            show_progress_details=False,
        )

        self.label_file_count = Gtk.Label()
        self.vbox.append(self.label_file_count)

        self.cancel_button = Gtk.Button(label=_("Cancel"))
        self.cancel_handler_id = self.cancel_button.connect("clicked", self.on_cancel_clicked)
        self.vbox.append(self.cancel_button)

        self.start_combination()

    def on_cancel_clicked(self, widget):
        if self.thread and self.thread.is_alive():
            self.thread.stop()
        self.cancel_button.set_sensitive(False)

    def start_combination(self):
        video_file = None
        audio_files = []

        for file in self.files:
            path = file.get_location().get_path()
            if file.get_mime_type().startswith('video/'):
                video_file = path
            elif file.get_mime_type().startswith('audio/'):
                audio_files.append(path)

        if not video_file or not audio_files:
            self.label_file_count.set_text(_("Error: Please select one video and at least one audio file."))
            GLib.timeout_add(2000, self.close)
            return

        duration = get_duration(video_file)
        video_ext = os.path.splitext(video_file)[1]
        output_path = os.path.splitext(video_file)[0] + f"_combined{video_ext}"

        kwargs = {
            'video_file': video_file,
            'audio_files': audio_files,
            'destination': output_path,
            'duration': duration * 1000,
            'source': video_file,
            'start-time': '',
            'end-time': '',
            'args': ['', None],
        }

        self._start_ffmpeg([kwargs], cmd_builder=combiner_pass)

    def update_count(self, count, duration, status):
        from common import Status
        if status == Status.ERROR:
            self.label_file_count.set_text(_("Error: {0}").format(count))
        elif status == Status.DONE:
            self.label_file_count.set_text(_("Done!"))
        else:
            self.label_file_count.set_text(count)

    def end_conversion(self, filedone):
        self.cancel_button.set_label(_("Close"))
        self.cancel_button.set_sensitive(True)
        if self.cancel_handler_id > 0:
            self.cancel_button.disconnect(self.cancel_handler_id)
            self.cancel_handler_id = 0
        GLib.timeout_add(1000, self.close)


class VideoAudioCombinerExtension(GObject.GObject, Nautilus.MenuProvider):
    def __init__(self):
        GObject.GObject.__init__(self)

    def get_file_items(self, files):
        if len(files) < 2:
            return []

        video_files = [f for f in files if f.get_mime_type().startswith('video/')]
        audio_files = [f for f in files if f.get_mime_type().startswith('audio/')]

        if len(video_files) != 1 or not audio_files:
            return []

        item = Nautilus.MenuItem(
            name='VideoAudioCombinerExtension::Combine',
            label=_('Combine Audio/Video'),
            tip=_('Combines a video file and audio files')
        )
        item.connect('activate', self.show_combiner_window, files)

        return [item]

    def show_combiner_window(self, menu, files):
        win = CombinerWindow(files)
        win.set_visible(True)
