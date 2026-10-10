"""中文桌面界面：链接 → 视频预览 → 选择画质 → 下载。"""
import io
import copy
import os
import queue
import threading
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageDraw, ImageOps, ImageTk
from collector import (DEFAULT_OUTPUT, ROOT, RESOURCE_ROOT, UPDATE_NOTICE, Settings, collect, error_hint, parse_inputs, settings_for_url,
                       preview_video, thumbnail_bytes)
from updater import current_version, update_latest
from site_config import load_config, save_config
from settings_ui import SiteSettings
from completion_notifications import DesktopNotifier

from ui_theme import FONT, apply_theme, get_palette, register_native, apply_native_theme
PLATFORMS = {'bilibili': '哔哩哔哩', 'youtube': 'YouTube', 'douyin': '抖音'}
STATUSES = {'downloaded': '已下载', 'metadata_saved': '信息已保存', 'failed': '失败',
            'skipped_archive': '已下载 · 跳过', 'duplicate': '重复链接', 'cancelled': '未执行'}


def duration_text(seconds):
    if seconds is None:
        return '—'
    hours, rest = divmod(max(0, int(seconds)), 3600)
    minutes, seconds = divmod(rest, 60)
    return f'{hours}:{minutes:02}:{seconds:02}' if hours else f'{minutes:02}:{seconds:02}'


def size_text(value):
    if value is None:
        return '大小未知'
    return f'{value / 1048576:.1f} MB' if value < 1073741824 else f'{value / 1073741824:.2f} GB'


class App:
    def __init__(self, root):
        self.root = root
        if os.name == 'nt':
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('VideoCollector.Desktop')
            root.iconbitmap(default=str(RESOURCE_ROOT / 'assets' / 'video-collector.ico'))
        self.app_icon = tk.PhotoImage(file=str(RESOURCE_ROOT / 'assets' / 'video-collector-window.png'))
        root.iconphoto(True, self.app_icon)
        root.title('视频采集器 · 视频工作台')
        width = min(1240, max(960, root.winfo_screenwidth() - 80))
        height = min(840, max(600, root.winfo_screenheight() - 120))
        root.geometry(f'{width}x{height}')
        root.minsize(960, 600)
        self.events, self.stop = queue.Queue(), threading.Event()
        self.running, self.items, self.logs = False, {}, []
        self.config = load_config(ROOT / 'settings.json')
        self.notifications_enabled = tk.BooleanVar(value=self.config.get('completion_notifications', True))
        self.notifier = DesktopNotifier(root, RESOURCE_ROOT / 'assets' / 'video-collector.ico')
        self._batch_counter, self._last_completed_batch = 0, 0
        self.theme_mode = self.config.get('theme', 'light')
        self.palette = get_palette(self.theme_mode)
        register_native(root, bg='bg')
        self.cover_image, self.quality_map = None, {}
        self._cover_bytes, self._cover_size = None, None
        self._cover_placeholder = '添加链接，开启视频预览'
        self.output = tk.StringVar(value=str(DEFAULT_OUTPUT))
        self.cookies, self.proxy, self.node = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.quality, self.mode = tk.StringVar(value='解析后选择画质'), tk.StringVar(value='video')
        self.status = tk.StringVar(value=UPDATE_NOTICE or '准备好了，添加链接即可开始。')
        self.version_text = tk.StringVar(value='yt-dlp ' + current_version())
        self.queue_count = tk.StringVar(value='0 个视频')
        self.progress_title = tk.StringVar(value='等待开始')
        self.progress_detail = tk.StringVar(value='下载进度、速度和剩余时间将在这里显示')
        self.percent = tk.StringVar(value='—')
        self.style()
        outer = ttk.Frame(root, padding=(18, 14), style='Page.TFrame')
        outer.pack(fill='both', expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)
        header = ttk.Frame(outer, padding=(16, 12), style='Header.TFrame')
        header.grid(row=0, column=0, sticky='ew', pady=(0, 16))
        header.columnconfigure(1, weight=1)
        self.brand_icon = self.app_icon.subsample(7, 7)
        self.native(tk.Label(header, image=self.brand_icon, borderwidth=0), bg='navy').grid(row=0, column=0, rowspan=2, padx=(0, 12))
        ttk.Label(header, text='视频采集器', style='Hero.TLabel').grid(row=0, column=1, sticky='w')
        ttk.Label(header, text='哔哩哔哩  /  YouTube  /  抖音', style='HeaderMuted.TLabel').grid(row=1, column=1, sticky='w', pady=(3, 0))
        tools = ttk.Frame(header, style='Header.TFrame')
        tools.grid(row=0, column=2, rowspan=2, sticky='e')
        self.theme_button = ttk.Button(tools, text='亮色模式' if self.theme_mode == 'dark' else '暗色模式',
                                       style='Header.TButton', command=self.toggle_theme)
        self.theme_button.grid(row=0, column=0, padx=(0, 8))
        self.update_button = ttk.Button(tools, text='检查更新', style='Header.TButton', command=self.start_update)
        self.update_button.grid(row=0, column=1, padx=(0, 8))
        self.settings_button = ttk.Button(tools, text='站点设置', style='Header.TButton', command=self.connection_settings)
        self.settings_button.grid(row=0, column=2)
        ttk.Label(tools, textvariable=self.version_text, style='HeaderMuted.TLabel').grid(row=1, column=0, columnspan=3, sticky='e', pady=(6, 0))
        main = ttk.Frame(outer, style='Page.TFrame')
        main.grid(row=1, column=0, sticky='nsew')
        main.columnconfigure(0, weight=2, minsize=310)
        main.columnconfigure(1, weight=3, minsize=430)
        main.rowconfigure(0, weight=1)
        left = ttk.Frame(main, padding=(14, 12), style='Card.TFrame')
        left.grid(row=0, column=0, sticky='nsew', padx=(0, 16))
        right = ttk.Frame(main, padding=(12, 16, 12, 12), style='Card.TFrame')
        right.grid(row=0, column=1, sticky='nsew')
        self.build_input(left)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        self.preview_canvas = self.native(tk.Canvas(right, highlightthickness=0, width=1, height=1), bg='card')
        self.preview_canvas.grid(row=0, column=0, sticky='nsew')
        preview_scroll = ttk.Scrollbar(right, orient='vertical', command=self.preview_canvas.yview)
        preview_scroll.grid(row=0, column=1, sticky='ns')
        self.preview_canvas.configure(yscrollcommand=preview_scroll.set)
        self.preview_body = ttk.Frame(self.preview_canvas, padding=(4, 0, 12, 10), style='Card.TFrame')
        self.preview_window = self.preview_canvas.create_window((0, 0), window=self.preview_body, anchor='nw')
        self.preview_body.bind('<Configure>', lambda _: self.preview_canvas.configure(scrollregion=self.preview_canvas.bbox('all')))
        self.preview_canvas.bind('<Configure>', self.resize_preview)
        root.bind('<MouseWheel>', self.scroll_preview, add='+')
        self.build_preview(self.preview_body)
        options = ttk.Frame(right, padding=(4, 10, 0, 0), style='Card.TFrame')
        options.grid(row=1, column=0, columnspan=2, sticky='ew')
        self.build_download_options(options)
        self.build_download_actions(right)
        self.progress_panel = progress = ttk.Frame(outer, padding=(16, 10), style='Card.TFrame')
        progress.grid(row=2, column=0, sticky='ew', pady=(14, 0))
        row = ttk.Frame(progress, style='Card.TFrame')
        row.pack(fill='x')
        row.columnconfigure(0, weight=1)
        self.progress_heading = ttk.Label(row, textvariable=self.progress_title, style='Section.TLabel', width=1)
        self.progress_heading.grid(row=0, column=0, sticky='ew')
        ttk.Label(row, textvariable=self.percent, style='Badge.TLabel').grid(row=0, column=1, padx=12)
        self.log_button = ttk.Button(row, text='运行日志', style='Ghost.TButton', command=self.show_logs)
        self.log_button.grid(row=0, column=2, padx=(0, 8))
        self.stop_button = ttk.Button(row, text='本条完成后停止', style='Danger.TButton', command=self.request_stop, state='disabled')
        self.stop_button.grid(row=0, column=3)
        self.progress = ttk.Progressbar(progress, maximum=100, style='Blue.Horizontal.TProgressbar')
        self.progress.pack(fill='x', pady=(10, 8))
        detail_row = ttk.Frame(progress, style='Card.TFrame')
        detail_row.pack(fill='x')
        detail_row.columnconfigure(0, weight=1)
        self.detail_label = ttk.Label(detail_row, textvariable=self.progress_detail, style='Muted.TLabel', width=1)
        self.detail_label.grid(row=0, column=0, sticky='ew')
        self.notify_toggle = ttk.Checkbutton(detail_row, text='完成提醒', variable=self.notifications_enabled,
                                            command=self.save_notification_preference)
        self.notify_toggle.grid(row=0, column=1, sticky='e', padx=(12, 0))
        self.status_label = ttk.Label(outer, textvariable=self.status, style='PageMuted.TLabel', width=1)
        self.status_label.grid(row=3, column=0, sticky='ew', pady=(8, 0))
        for widget, variable in ((self.status_label, self.status), (self.detail_label, self.progress_detail),
                                 (self.progress_heading, self.progress_title)):
            self.bind_text_hint(widget, variable)
        outer.bind('<Configure>', self.resize_status)
        self.mode.trace_add('write', lambda *_: self.update_buttons())
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(80, self.poll)

    def resize_status(self, event):
        # 底栏保持一行高，长提示不挤压输入区和队列；完整过程在日志查看。
        self.status_label.configure(wraplength=0)
        self.detail_label.configure(wraplength=0)
        self.progress_heading.configure(wraplength=0)

    def bind_text_hint(self, widget, variable):
        pending, popup = [None], [None]

        def hide(_=None):
            if pending[0] is not None:
                widget.after_cancel(pending[0])
                pending[0] = None
            if popup[0] is not None:
                popup[0].destroy()
                popup[0] = None

        def show():
            pending[0] = None
            popup[0] = tk.Toplevel(self.root)
            popup[0].withdraw()
            popup[0].overrideredirect(True)
            text = variable.get() if hasattr(variable, 'get') else variable.cget('text')
            self.native(tk.Label(popup[0], text=text, font=(FONT, 9),
                                 padx=12, pady=8, wraplength=540, justify='left'),
                        bg='navy', fg='header_ink').pack()
            popup[0].update_idletasks()
            x = min(widget.winfo_rootx(), self.root.winfo_screenwidth() - popup[0].winfo_reqwidth() - 12)
            y = widget.winfo_rooty() - popup[0].winfo_reqheight() - 8
            popup[0].geometry(f'+{max(0, x)}+{max(0, y)}')
            popup[0].deiconify()

        def enter(_):
            hide()
            pending[0] = widget.after(550, show)

        widget.bind('<Enter>', enter, add='+')
        widget.bind('<Leave>', hide, add='+')
        widget.bind('<Button-1>', hide, add='+')

    def resize_preview(self, event):
        self.preview_canvas.itemconfigure(self.preview_window, width=event.width)
        width = max(180, event.width - 16)
        for label in (self.title_label, self.author_label, self.description):
            label.configure(wraplength=width)
        self.render_cover(width)

    def scroll_preview(self, event):
        widget = event.widget
        while widget is not None:
            if widget in (self.preview_body, self.preview_canvas):
                if self.preview_canvas.yview() != (0.0, 1.0):
                    self.preview_canvas.yview_scroll(-int(event.delta / 120), 'units')
                return 'break'
            widget = getattr(widget, 'master', None)

    def style(self):
        self.palette = get_palette(self.theme_mode)
        apply_theme(self.root, self.theme_mode)
        apply_native_theme(self.root, self.palette)
        self.update_tree_colors()
        if dialog := getattr(self, 'site_dialog', None):
            if not dialog._closed:
                dialog.apply_theme()

    def native(self, widget, **roles):
        register_native(widget, **roles)
        apply_native_theme(widget, self.palette)
        return widget

    def update_tree_colors(self):
        if not hasattr(self, 'tree'):
            return
        for tag, role in [('ready', 'green'), ('failed', 'red'), ('working', 'blue'), ('muted', 'muted')]:
            self.tree.tag_configure(tag, foreground=self.palette[role])

    def toggle_theme(self):
        self.theme_mode = 'light' if self.theme_mode == 'dark' else 'dark'
        self.config['theme'] = self.theme_mode
        self.style()
        self.show_cover(self._cover_bytes, self._cover_placeholder)
        self.theme_button.configure(text='亮色模式' if self.theme_mode == 'dark' else '暗色模式')
        label = '暗色' if self.theme_mode == 'dark' else '亮色'
        try:
            save_config(ROOT / 'settings.json', self.config)
        except OSError as exc:
            self.status.set(f'已切换到{label}模式；偏好保存失败，本次仍可使用。')
            self.log_event('界面模式偏好保存失败：' + str(exc))
        else:
            self.status.set(f'已切换到{label}模式，下次启动会使用这个模式。')

    def save_notification_preference(self):
        self.config['completion_notifications'] = self.notifications_enabled.get()
        state = '开启' if self.notifications_enabled.get() else '关闭'
        try:
            save_config(ROOT / 'settings.json', self.config)
        except OSError as exc:
            self.status.set(f'完成提醒已{state}；偏好保存失败，本次仍可使用。')
            self.log_event('完成提醒偏好保存失败：' + str(exc))
        else:
            self.status.set(f'完成提醒已{state}，下次启动会保留这个选择。')

    @staticmethod
    def batch_summary(counts):
        success = counts.get('downloaded', 0) + counts.get('metadata_saved', 0)
        skipped = counts.get('skipped_archive', 0) + counts.get('duplicate', 0)
        message = f"成功 {success} 个 · 失败 {counts.get('failed', 0)} 个 · 跳过 {skipped} 个"
        if counts.get('cancelled', 0):
            message += f" · 未执行 {counts['cancelled']} 个"
        return message

    def notify_batch_complete(self, batch):
        if not self.notifications_enabled.get():
            return
        heading = '任务已停止' if batch['stopped'] else ('下载完成' if batch.get('mode', 'video') == 'video' else '信息保存完成')
        title = '视频采集器 · ' + heading
        message = self.batch_summary(batch['counts']) + '\n保存位置：' + batch['output']
        try:
            delivered = self.notifier.show(title, message)
        except Exception as exc:
            delivered = False
            self.log_event('系统完成提醒未发送：' + str(exc))
        if not delivered:
            try:
                self.show_completion_fallback(title, message)
            except tk.TclError:
                self.log_event('完成提醒窗口未能显示，任务摘要已保留在状态栏和日志中。')

    def show_completion_fallback(self, title, message):
        # 非模态提示不会阻塞下一批任务；系统通知不可用时仍能在程序中看到摘要。
        previous = getattr(self, 'completion_popup', None)
        if previous and previous.winfo_exists():
            previous.destroy()
        popup = self.completion_popup = tk.Toplevel(self.root)
        popup.withdraw()
        popup.title(title)
        popup.transient(self.root)
        popup.resizable(False, False)
        dismiss_job = [None]

        def cancel_timer(event=None):
            if event is not None and event.widget != popup:
                return
            if dismiss_job[0] is not None:
                popup.after_cancel(dismiss_job[0])
                dismiss_job[0] = None

        popup.bind('<Destroy>', cancel_timer, add='+')
        self.native(popup, bg='card')
        body = ttk.Frame(popup, padding=20, style='Card.TFrame')
        body.pack(fill='both', expand=True)
        ttk.Label(body, text=title, style='Section.TLabel').pack(anchor='w')
        ttk.Label(body, text=message, style='TLabel', justify='left', wraplength=400).pack(fill='x', pady=(10, 14))
        ttk.Button(body, text='关闭', command=popup.destroy).pack(anchor='e')
        popup.update_idletasks()
        x = max(0, min(self.root.winfo_rootx() + self.root.winfo_width() - popup.winfo_reqwidth() - 20,
                       self.root.winfo_screenwidth() - popup.winfo_reqwidth() - 20))
        y = max(0, min(self.root.winfo_rooty() + self.root.winfo_height() - popup.winfo_reqheight() - 30,
                       self.root.winfo_screenheight() - popup.winfo_reqheight() - 60))
        popup.geometry(f'+{x}+{y}')
        popup.deiconify()
        dismiss_job[0] = popup.after(12000, popup.destroy)

    def section_heading(self, parent, number, title):
        row = ttk.Frame(parent, style='Card.TFrame')
        ttk.Label(row, text=number, style='Step.TLabel').pack(side='left', padx=(0, 9))
        ttk.Label(row, text=title, style='Section.TLabel').pack(side='left')
        return row

    def build_input(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1, minsize=56)
        parent.rowconfigure(5, weight=3, minsize=74)
        self.section_heading(parent, '01', '添加视频链接').grid(row=0, column=0, sticky='ew')
        parent.rowconfigure(1, minsize=10)
        entry = self.native(tk.Frame(parent, highlightthickness=1), bg='input', highlightbackground='border')
        entry.grid(row=2, column=0, sticky='nsew')
        entry.columnconfigure(0, weight=1)
        entry.rowconfigure(0, weight=1)
        self.links = self.native(tk.Text(entry, height=4, width=1, wrap='word', font=(FONT, 10),
                                        relief='flat', padx=12, pady=12, borderwidth=0),
                                 bg='input', fg='ink', insertbackground='blue',
                                 selectbackground='selection', selectforeground='ink')
        self.links.grid(row=0, column=0, sticky='nsew')
        scrollbar = ttk.Scrollbar(entry, orient='vertical', command=self.links.yview)
        scrollbar.grid(row=0, column=1, sticky='ns')
        self.links.configure(yscrollcommand=scrollbar.set)
        self.link_hint = self.native(tk.Label(self.links, text='在这里粘贴视频链接'+chr(10)+'每行一条，支持批量添加',
                                              font=(FONT, 9), justify='left', anchor='nw'),
                                     bg='input', fg='input_hint')
        self.link_hint.place(x=12, y=12)
        self.link_hint.bind('<Button-1>', lambda _: self.links.focus_set())
        for event in ('<KeyRelease>', '<FocusIn>', '<FocusOut>'):
            self.links.bind(event, self.update_link_hint, add='+')
        row = ttk.Frame(parent, style='Card.TFrame')
        row.grid(row=3, column=0, sticky='ew', pady=(8, 10))
        row.columnconfigure(0, weight=1)
        self.preview_button = ttk.Button(row, text='获取视频预览', style='Accent.TButton', command=self.start_preview)
        self.preview_button.grid(row=0, column=0, sticky='ew')
        self.import_button = ttk.Button(row, text='导入 TXT', style='Ghost.TButton', command=self.import_file)
        self.import_button.grid(row=0, column=1, padx=(8, 0))
        row = self.section_heading(parent, '02', '视频队列')
        row.grid(row=4, column=0, sticky='ew', pady=(0, 8))
        ttk.Label(row, textvariable=self.queue_count, style='Muted.TLabel').pack(side='right')
        table = ttk.Frame(parent, style='Card.TFrame')
        table.grid(row=5, column=0, sticky='nsew')
        self.tree = ttk.Treeview(table, columns=('title', 'status'), show='headings', selectmode='browse', height=7)
        for name, title, width in [('title', '视频标题', 190), ('status', '状态', 94)]:
            self.tree.heading(name, text=title)
            self.tree.column(name, width=width, minwidth=70, stretch=name == 'title')
        scroll = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.update_tree_colors()
        self.queue_empty = self.native(tk.Label(self.tree, text='队列还没有视频'+chr(10)+'解析链接后，在这里选择要下载的视频',
                                                font=(FONT, 9), justify='center', wraplength=230),
                                       fg='muted', bg='card')
        self.queue_empty.place(relx=.5, rely=.58, anchor='center')
        self.tree.bind('<<TreeviewSelect>>', lambda _: self.render_selection())

    def update_link_hint(self, _=None):
        if self.links.get('1.0', 'end').strip() or self.root.focus_get() == self.links:
            self.link_hint.place_forget()
        else:
            self.link_hint.place(x=12, y=12)

    def refresh_queue(self):
        total = len(self.items)
        self.queue_count.set(f'{total} 个视频')
        if total:
            self.queue_empty.place_forget()
        else:
            self.queue_empty.place(relx=.5, rely=.58, anchor='center')

    def set_row_status(self, key, status):
        self.tree.set(key, 'status', status)
        tag = ('failed' if '失败' in status or '无效' in status else 'working' if status in ('处理中', '读取信息')
               else 'ready' if status in ('就绪', '已下载', '已下载 · 跳过', '信息已保存') else 'muted')
        self.tree.item(key, tags=(tag,))

    def build_preview(self, parent):
        row = ttk.Frame(parent, style='Card.TFrame')
        row.pack(fill='x')
        ttk.Label(row, text='视频详情', style='Section.TLabel').pack(side='left')
        self.platform_label = ttk.Label(row, text='等待预览', style='Badge.TLabel')
        self.platform_label.pack(side='right')
        self.cover = self.native(tk.Label(parent, font=(FONT, 9), compound='bottom', borderwidth=0), bg='cover', fg='cover_text')
        self.cover.pack(fill='x', pady=(14, 16))
        self.show_cover(None, '添加链接，开启视频预览')
        self.title_label = ttk.Label(parent, text='每个喜欢的视频，都值得保存。', style='Title.TLabel', wraplength=510)
        self.title_label.pack(anchor='w', fill='x')
        self.author_label = ttk.Label(parent, text='作者 —    ·    时长 —', style='Muted.TLabel')
        self.author_label.pack(anchor='w', fill='x', pady=(8, 10))
        self.description = ttk.Label(parent, text='先获取预览，查看视频信息与可用画质。', wraplength=510, style='Muted.TLabel')
        self.description.pack(anchor='w', fill='x', pady=(0, 14))

    def build_download_options(self, parent):
        ttk.Separator(parent).pack(fill='x', pady=(0, 10))
        row = ttk.Frame(parent, style='Card.TFrame')
        row.pack(fill='x')
        ttk.Label(row, text='下载画质', style='Section.TLabel').pack(side='left')
        self.quality_combo = ttk.Combobox(row, textvariable=self.quality, state='disabled', width=18)
        self.quality_combo.pack(side='right')
        self.quality_combo.bind('<<ComboboxSelected>>', self.set_quality)
        self.quality_note = ttk.Label(parent, text='解析后显示当前可用清晰度', style='Muted.TLabel', width=1)
        self.bind_text_hint(self.quality_combo, self.quality_note)
        row = ttk.Frame(parent, style='Card.TFrame')
        row.pack(fill='x', pady=(6, 6))
        self.mode_buttons = []
        for text, value in [('视频 + 信息', 'video'), ('仅保存信息', 'metadata')]:
            button = ttk.Radiobutton(row, text=text, variable=self.mode, value=value)
            button.pack(side='left', padx=(0, 16))
            self.mode_buttons.append(button)
        row = ttk.Frame(parent, style='Card.TFrame')
        row.pack(fill='x')
        ttk.Label(row, text='保存位置', style='TLabel').pack(side='left', padx=(0, 8))
        self.output_entry = ttk.Entry(row, textvariable=self.output)
        self.output_entry.pack(side='left', fill='x', expand=True)
        self.choose_output_button = ttk.Button(row, text='选择文件夹', command=self.choose_output)
        self.output_button = self.choose_output_button
        self.choose_output_button.pack(side='left', padx=(8, 0))

    def build_download_actions(self, parent):
        row = ttk.Frame(parent, padding=(4, 10, 0, 0), style='Card.TFrame')
        row.grid(row=2, column=0, columnspan=2, sticky='ew')
        row.columnconfigure(0, weight=1)
        self.download_button = ttk.Button(row, text='下载所选', style='Accent.TButton', command=lambda: self.start_download([self.selected()]), state='disabled')
        self.download_button.grid(row=0, column=0, sticky='ew')
        self.all_button = ttk.Button(row, text='下载全部', command=lambda: self.start_download(list(self.items)), state='disabled')
        self.all_button.grid(row=0, column=1, padx=8)
        self.open_button = ttk.Button(row, text='打开目录', style='Ghost.TButton', command=self.open_output)
        self.open_button.grid(row=0, column=2)

    def show_cover(self, data, placeholder='暂无封面，不影响下载'):
        self._cover_bytes, self._cover_placeholder = data, placeholder
        self._cover_size = None
        width = max(180, self.preview_canvas.winfo_width() - 16) if self.preview_canvas.winfo_width() > 1 else 520
        self.render_cover(width)

    def render_cover(self, width):
        width = max(160, min(760, int(width)))
        height = min(220 if self._cover_bytes else 140, round(width * 9 / 16))
        if self._cover_size == (width, height):
            return
        self._cover_size = (width, height)
        canvas = Image.new('RGB', (width, height), self.palette['cover'])
        text = self._cover_placeholder
        if self._cover_bytes:
            try:
                with Image.open(io.BytesIO(self._cover_bytes)) as im:
                    im = ImageOps.contain(im.convert('RGB'), canvas.size)
                    canvas.paste(im, ((width - im.width) // 2, (height - im.height) // 2))
                text = ''
            except Exception:
                text = '封面无法显示，不影响下载'
        else:
            drawing = ImageDraw.Draw(canvas)
            cx, cy = width // 2, height // 2
            drawing.ellipse((cx - 33, cy - 33, cx + 33, cy + 33), fill=self.palette['cover_circle'],
                            outline=self.palette['cover_outline'], width=2)
            drawing.polygon([(cx - 9, cy - 16), (cx - 9, cy + 16), (cx + 17, cy)], fill=self.palette['cover_play'])
            drawing.line((24, height - 22, width - 24, height - 22), fill=self.palette['cover_line'], width=1)
        self.cover_image = ImageTk.PhotoImage(canvas)
        self.cover.configure(image=self.cover_image, text=text, pady=8 if text else 0)

    def settings(self):
        if not self.output.get().strip():
            raise ValueError('请选择保存目录。')
        return Settings(output=Path(self.output.get().strip()), download=self.mode.get() == 'video',
                        site_profiles=copy.deepcopy(self.config['sites']))

    def selected(self):
        selection = self.tree.selection()
        return selection[0] if selection else None

    def render_selection(self):
        item = self.items.get(self.selected(), {})
        data = item.get('preview')
        self.show_cover(item.get('cover'), '封面加载中' if data and not item.get('cover_done') else '暂无封面，不影响下载')
        if data:
            title = data.get('title') or '未命名视频'
            self.title_label.configure(text=title)
            author = (data.get('uploader') or '未知')[:36]
            self.author_label.configure(text=f"作者 {author}    ·    时长 {duration_text(data.get('duration'))}")
            self.platform_label.configure(text=PLATFORMS.get(data.get('platform'), '视频'))
            desc = ' '.join((data.get('description') or '暂无简介').split())
            self.description.configure(text=desc[:90] + ('…' if len(desc) > 90 else ''))
            self.quality_map = {'最高可用画质': 'best', **{q['label']: str(q['height']) for q in data['qualities']}}
            self.quality_combo.configure(values=list(self.quality_map))
            self.quality.set(next((label for label, key in self.quality_map.items() if key == item.get('quality')), '最高可用画质'))
            self.quality_note.configure(text=f"可用分辨率 {len(data['qualities'])} 档 · 按所选上限匹配格式" if data['qualities'] else '平台未提供分辨率信息，将选择最高可用格式')
        else:
            self.title_label.configure(text='预览失败' if item.get('error') else '等待视频信息')
            self.author_label.configure(text='作者 —    ·    时长 —')
            self.platform_label.configure(text='待解析')
            self.description.configure(text=item.get('error', '先点击“获取视频预览”。')[:150])
            self.quality.set('解析后选择画质')
            self.quality_map = {}
            self.quality_note.configure(text='成功获取信息后即可选择清晰度')
        self.update_buttons()

    def set_quality(self, _=None):
        if item := self.items.get(self.selected()):
            item['quality'] = self.quality_map.get(self.quality.get(), 'best')

    def update_buttons(self):
        ready = bool(self.items.get(self.selected(), {}).get('preview'))
        video_mode = self.mode.get() == 'video'
        self.download_button.configure(text='下载所选' if video_mode else '保存所选', state='normal' if ready and not self.running else 'disabled')
        self.all_button.configure(text='下载全部' if video_mode else '保存全部', state='normal' if not self.running and any(i.get('preview') for i in self.items.values()) else 'disabled')
        self.quality_combo.configure(state='readonly' if ready and not self.running else 'disabled')
        for widget in (self.preview_button, self.import_button, self.update_button):
            widget.configure(state='disabled' if self.running else 'normal')
        self.stop_button.configure(state='normal' if self.running and not self.stop.is_set() else 'disabled')

    def begin(self, message):
        self.running = True
        self.stop.clear()
        self.status.set(message)
        self.update_buttons()

    def start_update(self):
        if self.running:
            return
        self.begin('正在检查采集组件更新…')
        self.progress_title.set('检查并更新 yt-dlp')
        self.progress_detail.set('从 PyPI 官方获取版本，校验后安装；重启程序生效')
        self.indeterminate()
        self.stop_button.configure(state='disabled')
        proxy = self.config.get('update_proxy') or None

        def worker():
            try:
                result = update_latest(ROOT / 'updates', proxy=proxy, emit=lambda msg: self.events.put(('update_status', msg)))
                self.events.put(('updated', result))
            except Exception as exc:
                self.log_event('更新失败：' + str(exc))
                self.events.put(('done', '更新失败，当前版本仍可使用。请检查网络或日志。'))
        threading.Thread(target=worker, daemon=True).start()

    def start_preview(self):
        if self.running:
            return
        try:
            settings = self.settings()
            urls, errors = parse_inputs(self.links.get('1.0', 'end'))
            if not urls and not errors:
                raise ValueError('请先粘贴视频链接。')
        except ValueError as exc:
            messagebox.showinfo('还需要一点信息', str(exc))
            return
        self.tree.delete(*self.tree.get_children())
        self.items = {}
        for index, url in enumerate(urls):
            key = str(index)
            self.items[key] = {'url': url, 'quality': 'best'}
            self.tree.insert('', 'end', iid=key, values=(url, '等待预览'), tags=('muted',))
        for index, error in enumerate(errors):
            key = f'error{index}'
            self.items[key] = {'url': error['input'], 'error': error['error']}
            self.tree.insert('', 'end', iid=key, values=(error['input'], '链接无效'), tags=('failed',))
        if self.items:
            self.tree.selection_set(next(iter(self.items)))
        self.update_link_hint()
        self.refresh_queue()
        self.begin('正在读取视频信息，尚未下载视频')
        self.render_selection()
        self.progress_title.set('正在获取预览')
        self.progress_detail.set('读取标题、封面、作者、时长和可用清晰度')
        self.indeterminate()
        threading.Thread(target=self.preview_worker, args=(urls, settings), daemon=True).start()

    def preview_worker(self, urls, settings):
        ready = 0
        try:
            for index, url in enumerate(urls):
                if self.stop.is_set():
                    for pending in range(index, len(urls)):
                        self.events.put(('row_status', (str(pending), '未执行')))
                    break
                key = str(index)
                self.events.put(('row_status', (key, '读取信息')))
                try:
                    data = preview_video(url, settings, emit=self.log_event)
                    self.events.put(('preview', (key, data)))
                    ready += 1
                    cover = None
                    try:
                        cover = thumbnail_bytes(data.get('thumbnail'), settings_for_url(settings, url).proxy)
                    except Exception as exc:
                        self.log_event('封面加载失败：' + str(exc))
                    self.events.put(('cover', (key, cover)))
                except Exception as exc:
                    self.log_event(f'{url}\n{exc}\n{error_hint(str(exc))}')
                    self.events.put(('preview_error', (key, error_hint(str(exc)))))
                if index + 1 < len(urls):
                    self.stop.wait(settings.interval)
        finally:
            self.events.put(('done', f'预览完成：{ready} 个视频就绪。选择画质后开始下载。'))

    def start_download(self, keys):
        if self.running:
            return
        jobs = [(key, dict(self.items[key])) for key in keys if key in self.items and self.items[key].get('preview')]
        if not jobs:
            return
        try:
            settings = self.settings()
        except ValueError as exc:
            messagebox.showinfo('保存位置', str(exc))
            return
        self.begin(f'已开始处理 {len(jobs)} 个视频')
        self.progress['value'] = 0
        self._batch_counter += 1
        threading.Thread(target=self.download_worker, args=(jobs, settings, self._batch_counter), daemon=True).start()

    def download_worker(self, jobs, settings, batch_id=None):
        if batch_id is None:
            self._batch_counter += 1
            batch_id = self._batch_counter
        counts = {}
        for index, (key, item) in enumerate(jobs):
            if self.stop.is_set():
                counts['cancelled'] = counts.get('cancelled', 0) + len(jobs) - index
                for pending, _ in jobs[index:]:
                    self.events.put(('row_status', (pending, '未执行')))
                break
            self.events.put(('row_status', (key, '处理中')))

            def progress(event):
                event.update(index=index + 1, count=len(jobs), key=key)
                self.events.put(('progress', event))

            try:
                result = collect(item['preview']['url'], replace(settings, quality=item.get('quality', 'best')),
                                 emit=self.log_event, stop=self.stop, progress_emit=progress)
                for name, count in result['counts'].items():
                    counts[name] = counts.get(name, 0) + count
            except Exception as exc:
                self.log_event(f'{exc}\n{error_hint(str(exc))}')
                counts['failed'] = counts.get('failed', 0) + 1
                self.events.put(('row_status', (key, '失败')))
            if index + 1 < len(jobs):
                self.stop.wait(settings.interval)
        self.events.put(('batch_done', {'batch_id': batch_id, 'counts': counts, 'total': len(jobs),
                                       'output': str(settings.output), 'stopped': self.stop.is_set(),
                                       'mode': 'video' if settings.download else 'metadata'}))

    def log_event(self, message):
        self.events.put(('log', message))

    def indeterminate(self):
        if str(self.progress['mode']) != 'indeterminate':
            self.progress.configure(mode='indeterminate')
            self.progress.start(12)
        self.percent.set('…')

    def show_progress(self, event):
        stage = event['stage']
        prefix = f"[{event['index']}/{event['count']}] "
        if stage in ('extracting', 'processing'):
            self.progress_title.set(prefix + ('准备视频' if stage == 'extracting' else '正在合并音画 / 转换 MP4'))
            self.progress_detail.set('正在获取最新下载地址' if stage == 'extracting' else '文件已接收，正在完成处理，请稍候')
            self.indeterminate()
        elif stage == 'downloading':
            total, done = event.get('total'), event.get('downloaded', 0)
            self.progress_title.set(prefix + '正在下载当前文件')
            if total:
                self.progress.stop()
                self.progress.configure(mode='determinate')
                percent = min(100, 100 * done / total)
                self.progress['value'] = percent
                self.percent.set(f'{percent:.0f}%')
            else:
                self.indeterminate()
            speed = f"{size_text(event['speed'])}/s" if event.get('speed') else '计算速度中'
            eta = duration_text(event.get('eta'))
            self.progress_detail.set(f"{size_text(done)} / {size_text(total)}    ·    {speed}    ·    剩余 {eta}")
        else:
            self.progress.stop()
            self.progress.configure(mode='determinate')
            success = stage in ('downloaded', 'metadata_saved', 'skipped_archive')
            self.progress['value'] = 100 if success else 0
            self.percent.set('100%' if success else '—')
            self.progress_title.set(prefix + STATUSES.get(stage, stage))
            self.progress_detail.set(event.get('error') or ('已在下载记录中，本次跳过，未重复下载'
                                                         if stage == 'skipped_archive' else '文件与任务报告已保存'))
            if event.get('key') in self.items:
                self.set_row_status(event['key'], STATUSES.get(stage, stage))

    def poll(self):
        for _ in range(150):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'log':
                self.logs.append(str(value))
                self.logs = self.logs[-1500:]
                if getattr(self, 'log_window', None) and self.log_window.winfo_exists():
                    self.log_text.configure(state='normal')
                    self.log_text.insert('end', str(value) + '\n')
                    self.log_text.see('end')
                    self.log_text.configure(state='disabled')
            elif kind == 'row_status':
                self.set_row_status(value[0], value[1])
            elif kind == 'preview':
                key, data = value
                heights = [q['height'] for q in data['qualities'] if q['height'] <= 1080]
                self.items[key].update(preview=data, quality=str(max(heights)) if heights else 'best')
                self.tree.item(key, values=(data.get('title') or data['url'], '就绪'), tags=('ready',))
                if self.selected() == key:
                    self.render_selection()
            elif kind == 'cover':
                key, cover = value
                self.items[key].update(cover=cover, cover_done=True)
                if self.selected() == key:
                    self.render_selection()
            elif kind == 'preview_error':
                key, error = value
                self.items[key]['error'] = error
                self.set_row_status(key, '预览失败')
                if self.selected() == key:
                    self.render_selection()
            elif kind == 'progress':
                self.show_progress(value)
            elif kind == 'update_status':
                self.progress_detail.set(value)
            elif kind == 'updated':
                self.running = False
                self.progress.stop()
                self.progress.configure(mode='determinate', value=100)
                self.percent.set('100%')
                installed = value['status'] == 'installed'
                if installed:
                    self.version_text.set(f"yt-dlp {current_version()} → {value['version']}")
                message = (f"已安装 {value['version']}，关闭并重新打开程序后生效。" if installed else f"当前 {value['version']} 已是最新正式版。")
                self.status.set(message)
                self.progress_title.set('更新已就绪' if installed else '检查完成')
                self.progress_detail.set(message)
                self.update_buttons()
            elif kind in ('done', 'batch_done'):
                if kind == 'batch_done':
                    if value['batch_id'] <= self._last_completed_batch:
                        continue
                    self._last_completed_batch = value['batch_id']
                self.running = False
                self.progress.stop()
                self.status.set(self.batch_summary(value['counts']) if kind == 'batch_done' else value)
                stopped = value['stopped'] if kind == 'batch_done' else self.stop.is_set()
                self.progress_title.set('已停止' if stopped else '本次处理结束')
                if str(self.progress['mode']) == 'indeterminate':
                    self.progress.configure(mode='determinate', value=0)
                    self.percent.set('—')
                self.update_buttons()
                if kind == 'batch_done':
                    self.notify_batch_complete(value)
        self.root.after(80, self.poll)

    def connection_settings(self):
        if self.running:
            messagebox.showinfo('正在处理', '请等待当前操作完成后再修改连接设置。')
            return
        self.site_dialog = SiteSettings(self, ROOT)

    def choose_file(self, variable):
        if path := filedialog.askopenfilename():
            variable.set(path)

    def choose_output(self):
        if path := filedialog.askdirectory(parent=self.root, title='选择视频保存文件夹',
                                           initialdir=self.output.get().strip() or str(DEFAULT_OUTPUT)):
            self.output.set(path)

    def import_file(self):
        if path := filedialog.askopenfilename(filetypes=[('文本清单', '*.txt'), ('全部文件', '*.*')]):
            try:
                self.links.insert('end', '\n' + Path(path).read_text(encoding='utf-8-sig'))
                self.update_link_hint()
            except (OSError, UnicodeError) as exc:
                messagebox.showerror('导入失败', str(exc))

    def open_output(self):
        try:
            path = self.settings().output.expanduser().resolve()
            path.mkdir(parents=True, exist_ok=True)
            os.startfile(path)
        except (OSError, ValueError) as exc:
            messagebox.showerror('打开失败', str(exc))

    def show_logs(self):
        if getattr(self, 'log_window', None) and self.log_window.winfo_exists():
            self.log_window.lift()
            return
        self.log_window = tk.Toplevel(self.root)
        self.log_window.title('运行日志')
        self.log_window.geometry('850x480')
        self.log_window.minsize(600, 350)
        self.native(self.log_window, bg='bg')
        header = ttk.Frame(self.log_window, padding=(20, 14), style='Header.TFrame')
        header.pack(fill='x')
        ttk.Label(header, text='运行日志', style='Hero.TLabel').pack(side='left')
        ttk.Label(header, text='查看处理过程和错误详情', style='HeaderMuted.TLabel').pack(side='right')
        body = ttk.Frame(self.log_window, padding=16, style='Page.TFrame')
        body.pack(fill='both', expand=True)
        self.log_text = self.native(tk.Text(body, wrap='word', font=('Consolas', 10), padx=14, pady=14,
                                            relief='flat', borderwidth=0),
                                    bg='log_bg', fg='log_fg', selectbackground='log_selection',
                                    selectforeground='log_fg', insertbackground='log_fg')
        self.log_text.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(body, orient='vertical', command=self.log_text.yview)
        scroll.pack(side='right', fill='y')
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.insert('end', '\n'.join(self.logs))
        self.log_text.configure(state='disabled')

    def request_stop(self):
        self.stop.set()
        self.status.set('等待当前视频完成后停止…')
        self.update_buttons()

    def close(self):
        if self.running:
            self.request_stop()
        else:
            self.notifier.close()
            self.root.destroy()


if __name__ == '__main__':
    window = tk.Tk()
    App(window)
    window.mainloop()
