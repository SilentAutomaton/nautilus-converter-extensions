import gi
gi.require_version('Nautilus', '3.0')
gi.require_version('Gtk', '3.0')
from gi.repository import Nautilus, GObject, Gtk, GLib
import queue
import subprocess
import os
import shlex
from common import (
    setup_localisation,
    FFmpeg,
    ffmpeg_cmd_args,
)

_ = setup_localisation()

def combiner_pass(*args, **kwa):
    """
    Command builder for combiner pass.
    """
    _ = setup_localisation()
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


class CombinerWindow(Gtk.Window):
    def __init__(self, files):
        super().__init__(title=_("Combining Audio/Video"))
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
        
        self.cancel_button = Gtk.Button(label=_("Cancel"))
        self.cancel_handler_id = self.cancel_button.connect("clicked", self.on_cancel_clicked)
        vbox.pack_start(self.cancel_button, True, True, 0)

        self.start_combination()

    def on_cancel_clicked(self, widget):
        if hasattr(self, 'thread') and self.thread.is_alive():
            self.thread.stop()
        self.cancel_button.set_sensitive(False)

    def get_duration(self, input_path):
        try:
            duration_process = subprocess.run([
                'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1', input_path
            ], capture_output=True, text=True, check=True)
            return float(duration_process.stdout)
        except (subprocess.CalledProcessError, ValueError):
            return 0

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
            self.update_count(_("Error: Please select one video and at least one audio file."), 0, 'ERROR')
            GLib.timeout_add(2000, self.close)
            return

        duration = self.get_duration(video_file)
        video_format = os.path.splitext(video_file)[1]
        output_path = os.path.splitext(video_file)[0] + f"_combined{video_format}"

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

        self.thread = FFmpeg(self, self.progress_queue, [kwargs], cmd_builder=combiner_pass)
        GLib.timeout_add(100, self.update_progress_from_queue)

    def update_count(self, count, duration, end):
        if end == 'ERROR':
            self.label_file_count.set_text(_("Error: {0}").format(count))
        elif end == 'DONE':
            self.label_file_count.set_text(_("Done!"))
        else:
            self.label_file_count.set_text(count)

    def update_output(self, output, duration, status):
        # This is now a no-op, but needs to exist for FFmpeg class callbacks.
        pass

    def end_conversion(self, filedone):
        self.cancel_button.set_label(_("Close"))
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


class VideoAudioCombinerExtension(GObject.GObject, Nautilus.MenuProvider):
    def __init__(self):
        GObject.GObject.__init__(self)

    def get_file_items(self, window, files):
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
        win.show_all()
