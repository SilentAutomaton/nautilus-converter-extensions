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
    Status,
)

_ = setup_localisation()


# ─── Command builders ─────────────────────────────────────────────────────────

def separator_pass(*args, **kwa):
    cmd = ffmpeg_cmd_args()
    pass1 = cmd["ffmpeg_cmd"] + cmd["ffmpeg-default-args"].split()
    pass1.extend(['-i', kwa["source"]])
    pass1.extend(kwa["args"][0].split())
    pass1.append(kwa["destination"])

    count1 = _("Task {0}/{1}: {2}").format(args[0], args[1], kwa["task_name"])
    stamp1 = f'{count1}\n\n[COMMAND]:\n{" ".join(shlex.quote(arg) for arg in pass1)}'
    return {'pass1': pass1, 'count1': count1, 'stamp1': stamp1}


def combiner_pass(*args, **kwa):
    cmd = ffmpeg_cmd_args()
    pass1 = cmd["ffmpeg_cmd"] + cmd["ffmpeg-default-args"].split()
    pass1.extend(['-i', kwa["video_file"]])
    for audio_file in kwa["audio_files"]:
        pass1.extend(['-i', audio_file])
    pass1.extend(['-map', '0'])
    for i in range(len(kwa["audio_files"])):
        pass1.extend(['-map', f'{i + 1}:a'])
    pass1.extend(['-c', 'copy', kwa["destination"]])

    count1 = _("Combining \"{0}\" with {1} audio file(s)...").format(
        os.path.basename(kwa["video_file"]), len(kwa["audio_files"])
    )
    stamp1 = f'{count1}\n\n[COMMAND]:\n' + " ".join(shlex.quote(arg) for arg in pass1)
    return {'pass1': pass1, 'count1': count1, 'stamp1': stamp1}


# ─── Shared UI base for simple stream operations ──────────────────────────────

class _StreamsBaseWindow(BaseConverterWindow):
    """Shared base for Separator and Combiner windows."""

    def _init_ui(self, title_text, default_size=(450, 150)):
        self._total_tasks = 0
        self._done_tasks = 0

        # Progress UI: progress_bar + label_file_count
        self._setup_progress_ui()

        self.cancel_button = Gtk.Button(label=_("Cancel"))
        self._cancel_handler_id = self.cancel_button.connect("clicked", self._on_cancel)
        self.vbox.append(self.cancel_button)

    def _on_cancel(self, widget):
        if self.thread and self.thread.is_alive():
            self.thread.stop()
        self.cancel_button.set_sensitive(False)

    def update_count(self, count, duration, status):
        if status == Status.ERROR:
            self.label_file_count.set_text(_("Error: {0}").format(count))
        elif status == Status.DONE:
            self._done_tasks += 1
            if self._total_tasks > 0:
                self.progress_bar.set_fraction(self._done_tasks / self._total_tasks)
        else:  # CONTINUE
            self.label_file_count.set_text(count)

    def end_conversion(self, filedone):
        self.progress_bar.set_fraction(1.0)
        self.label_file_count.set_text(_("Done!"))
        self.cancel_button.set_label(_("Close"))
        self.cancel_button.set_sensitive(True)
        if self._cancel_handler_id > 0:
            self.cancel_button.disconnect(self._cancel_handler_id)
            self._cancel_handler_id = 0
        self.cancel_button.connect("clicked", lambda w: self.close())
        GLib.timeout_add(2000, self.close)


# ─── Separator ────────────────────────────────────────────────────────────────

class SeparatorWindow(_StreamsBaseWindow):
    def __init__(self, files):
        super().__init__(
            title=_("Separating Audio/Video"),
            files=files,
            default_size=(450, 150),
            show_progress_details=False,
        )
        self._init_ui(title_text=_("Separating Audio/Video"))
        self._start_separation()

    def _get_stream_info(self, input_path):
        try:
            result = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_streams', '-print_format', 'json', input_path],
                capture_output=True, text=True, check=True
            )
            return json.loads(result.stdout)['streams']
        except (subprocess.CalledProcessError, ValueError, KeyError):
            return []

    def _start_separation(self):
        tasks = []
        for file in self.files:
            input_path = file.get_location().get_path()
            base_path, ext = os.path.splitext(input_path)
            duration = get_duration(input_path)
            streams = self._get_stream_info(input_path)
            audio_streams = [s for s in streams if s['codec_type'] == 'audio']

            tasks.append({
                'source': input_path,
                'destination': f"{base_path}_video{ext}",
                'duration': duration * 1000,
                'args': ['-vcodec copy -an', None],
                'task_name': _("Extracting video track"),
                'start-time': '', 'end-time': '',
            })

            for i, stream in enumerate(audio_streams):
                try:
                    audio_fmt = subprocess.run(
                        ['ffprobe', '-v', 'error', '-select_streams', f'a:{i}',
                         '-show_entries', 'stream=codec_name',
                         '-of', 'default=noprint_wrappers=1:nokey=1', input_path],
                        capture_output=True, text=True, check=True
                    ).stdout.strip()
                except (subprocess.CalledProcessError, ValueError):
                    audio_fmt = 'aac'

                tasks.append({
                    'source': input_path,
                    'destination': f"{base_path}_audio_{i}.{audio_fmt}",
                    'duration': duration * 1000,
                    'args': [f'-map 0:{stream["index"]} -acodec copy', None],
                    'task_name': _("Extracting audio track {0}").format(i + 1),
                    'start-time': '', 'end-time': '',
                })

        if not tasks:
            self.label_file_count.set_text(_("Error: No streams found to separate."))
            GLib.timeout_add(2000, self.close)
            return

        self._total_tasks = len(tasks)
        self._start_ffmpeg(tasks, cmd_builder=separator_pass)


# ─── Combiner ─────────────────────────────────────────────────────────────────

class CombinerWindow(_StreamsBaseWindow):
    def __init__(self, files):
        super().__init__(
            title=_("Combining Audio/Video"),
            files=files,
            default_size=(450, 150),
            show_progress_details=False,
        )
        self._init_ui(title_text=_("Combining Audio/Video"))
        self._start_combination()

    def _start_combination(self):
        video_file = None
        audio_files = []
        for file in self.files:
            path = file.get_location().get_path()
            if file.get_mime_type().startswith('video/'):
                video_file = path
            elif file.get_mime_type().startswith('audio/'):
                audio_files.append(path)

        if not video_file or not audio_files:
            self.label_file_count.set_text(
                _("Error: Select one video and at least one audio file.")
            )
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
            'start-time': '', 'end-time': '',
            'args': ['', None],
        }
        self._total_tasks = 1
        self._start_ffmpeg([kwargs], cmd_builder=combiner_pass)


# ─── Nautilus Extension Classes ───────────────────────────────────────────────

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
            label=_('Extract Audio/Video Streams'),
            tip=_('Extract audio and video as separate files')
        )
        item.connect('activate', lambda menu, f: SeparatorWindow(f).set_visible(True), files)
        return [item]


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
            tip=_('Merge audio tracks into a video file')
        )
        item.connect('activate', lambda menu, f: CombinerWindow(f).set_visible(True), files)
        return [item]
