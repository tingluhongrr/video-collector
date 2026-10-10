"""保留 yt-dlp 的归档跳过原因，并确保新下载视频最终为 MP4。"""
from yt_dlp import YoutubeDL
from yt_dlp.postprocessor.ffmpeg import FFmpegVideoConvertorPP, FFmpegVideoRemuxerPP
from yt_dlp.utils import PostProcessingError


class VideoDownloader(YoutubeDL):
    def __init__(self, *args, **kwargs):
        self.archived_info = None
        super().__init__(*args, **kwargs)

    def in_download_archive(self, info_dict):
        matched = super().in_download_archive(info_dict)
        if matched:
            self.archived_info = dict(info_dict)
        return matched


class EnsureMP4PP(FFmpegVideoConvertorPP):
    def __init__(self, downloader):
        super().__init__(downloader, preferedformat='mp4')

    def run(self, info):
        if info['ext'].lower() == 'mp4':
            return [], info
        try:
            return FFmpegVideoRemuxerPP(self._downloader, preferedformat='mp4').run(info)
        except PostProcessingError:
            self.to_screen('无法直接封装为 MP4，正在转码；较长视频可能需要一些时间。')
            return super().run(info)
