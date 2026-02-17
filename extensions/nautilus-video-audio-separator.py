from gi.repository import Nautilus, GObject, Gtk, GLib
import subprocess
import os
import json
import shlex
from common import (
    setup_localisation,
    get_duration,
    ffmpeg_cmd_args,
    BaseConverterWindow,
)

_ = setup_localisation()


def separator_pass(*args, **kwa):
    """
    Command builder for separator pass.
    """
    cmd = ffmpeg_cmd_args()

    pass1 = cmd["ffmpeg_cmd"] + cmd["ffmpeg-default-args"].split()
    pass1.extend(['-i', kwa["source"]])
    pass1.extend(kwa["args"][0].split())
    pass1.append(kwa["destination"])

    count1 = (_("File {0}/{1}: {2}").format(args[0], args[1], kwa["task_name"]))
    stamp1 = f'{count1}\n\n[COMMAND]:\n{" ".join(shlex.quote(arg) for arg in pass1)}'

    return {'pass1': pass1, 'count1': count1, 'stamp1': stamp1}


class SeparatorWindow(BaseConverterWindow):
    def __init__(self, files):
        super().__init__(
            title=_("Separating Audio/Video"),
            files=files,
            default_size=(400, 100),
            show_progress_details=False,
        )

        self.label_file_count = Gtk.Label()
        self.vbox.append(self.label_file_count)

        self.cancel_button = Gtk.Button(label=_("Cancel"))
        self.cancel_handler_id = self.cancel_button.connect("clicked", self.on_cancel_clicked)
        self.vbox.append(self.cancel_button)

        self.start_separation()

    def on_cancel_clicked(self, widget):
        if self.thread and self.thread.is_alive():
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

    def start_separation(self):
        tasks = []
        for file in self.files:
            input_path = file.get_location().get_path()
            base_path, ext = os.path.splitext(input_path)
            duration = get_duration(input_path)

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
                'task_name': _("Separating video track"),
                'start-time': '',
                'end-time': '',
            })

            # Audio tasks
            for i, audio_stream in enumerate(audio_streams):
                audio_index = audio_stream['index']
                try:
                    audio_fmt = subprocess.run([
                        'ffprobe', '-v', 'error', '-select_streams', f'a:{i}', '-show_entries', 'stream=codec_name',
                        '-of', 'default=noprint_wrappers=1:nokey=1', input_path
                    ], capture_output=True, text=True, check=True).stdout.strip()
                except (subprocess.CalledProcessError, ValueError):
                    audio_fmt = 'aac'

                audio_output_path = f"{base_path}_audio_{i}.{audio_fmt}"
                audio_args = ['-map', f'0:{audio_index}', '-acodec', 'copy']
                tasks.append({
                    'source': input_path,
                    'destination': audio_output_path,
                    'duration': duration * 1000,
                    'args': [' '.join(audio_args), None],
                    'task_name': _("Separating audio track {0}").format(i + 1),
                    'start-time': '',
                    'end-time': '',
                })

        if not tasks:
            self.label_file_count.set_text(_("Error: No streams found to separate."))
            GLib.timeout_add(2000, self.close)
            return

        self._start_ffmpeg(tasks, cmd_builder=separator_pass)

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
