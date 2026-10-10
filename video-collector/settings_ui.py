"""三个站点各自的代理与 Cookie 管理窗口。"""
import copy
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from site_config import SITES, import_cookies, read_browser_cookies, save_config
from ui_theme import apply_native_theme, get_palette, register_native


class SiteSettings:
    def __init__(self, app, root_dir):
        self.app, self.root_dir = app, root_dir
        self.events, self.busy = queue.Queue(), False
        self._closed, self._poll_job = False, None
        self._scroll_views = {}
        self.palette = dict(getattr(app, 'palette', None) or get_palette(getattr(app, 'theme_mode', 'light')))
        self.dialog = tk.Toplevel(app.root)
        self.dialog.title('站点设置 · 视频采集器')
        self.dialog.geometry('850x700')
        self.dialog.minsize(730, 500)
        self.dialog.configure(background=self.palette['bg'])
        register_native(self.dialog, background='bg')
        self.dialog.transient(app.root)
        self.dialog.grab_set()
        self.dialog.protocol('WM_DELETE_WINDOW', self.close)
        self.dialog.bind('<Destroy>', self._destroyed, add='+')
        self.dialog.bind('<MouseWheel>', self._wheel, add='+')
        self._style()
        self.dialog.columnconfigure(0, weight=1)
        self.dialog.rowconfigure(1, weight=1)

        header = ttk.Frame(self.dialog, padding=(24, 17), style='Settings.Header.TFrame')
        header.grid(row=0, column=0, sticky='ew')
        ttk.Label(header, text='站点设置', style='Settings.HeaderTitle.TLabel').pack(anchor='w')
        ttk.Label(header, text='为每个平台管理独立的登录信息与网络连接',
                  style='Settings.HeaderNote.TLabel').pack(anchor='w', pady=(4, 0))
        body = ttk.Frame(self.dialog, padding=(20, 16, 20, 12), style='Settings.Page.TFrame')
        body.grid(row=1, column=0, sticky='nsew')
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        self.tabs = ttk.Notebook(body, style='Settings.TNotebook')
        self.tabs.grid(row=0, column=0, sticky='nsew')
        self.vars, self.buttons = {}, []
        self.note = tk.StringVar(value='Cookie 只用于对应站点；代理留空时使用系统网络设置。')
        for site, title in SITES.items():
            tab = self._tab(title)
            profile = app.config['sites'][site]
            values = {key: tk.StringVar(value=profile.get(key, '')) for key in ('cookies', 'proxy')}
            values['browser_profile'] = tk.StringVar()
            self.vars[site] = values

            card = self._card(tab, 'Cookie 登录', '导入登录信息后，使用你在 ' + title + ' 的访问权限。')
            ttk.Label(card, text='Cookie 文件', style='Settings.Field.TLabel').pack(anchor='w', pady=(12, 5))
            ttk.Entry(card, textvariable=values['cookies'], width=20).pack(fill='x')
            row = ttk.Frame(card, style='Settings.Card.TFrame')
            row.pack(fill='x', pady=(10, 0))
            for text, callback in [('导入 cookies.txt', lambda s=site: self.read_file(s)),
                                   ('停用 Cookie', lambda v=values['cookies']: v.set(''))]:
                button = ttk.Button(row, text=text, command=callback)
                button.pack(side='left', padx=(0, 8))
                self.buttons.append(button)

            card = self._card(tab, '从浏览器读取', '先在浏览器登录 ' + title + '，再选择对应的浏览器。')
            row = ttk.Frame(card, style='Settings.Card.TFrame')
            row.pack(fill='x', pady=(12, 0))
            for column, browser in enumerate(('chrome', 'edge', 'firefox')):
                row.columnconfigure(column, weight=1, uniform='browser')
                button = ttk.Button(row, text=browser.title(), command=lambda b=browser, s=site: self.read_browser(s, b))
                button.grid(row=0, column=column, sticky='ew', padx=(0, 8 if column < 2 else 0))
                self.buttons.append(button)
            ttk.Label(card, text='浏览器配置目录 · 可选', style='Settings.Field.TLabel').pack(anchor='w', pady=(12, 5))
            ttk.Entry(card, textvariable=values['browser_profile'], width=20).pack(fill='x')
            self._hint(card, '留空自动查找；多账号可指定 Profile 目录。读取前建议关闭浏览器。', pady=(6, 0))

            card = self._card(tab, '站点代理', '只应用于 ' + title + ' 的视频与封面请求。')
            ttk.Entry(card, textvariable=values['proxy'], width=20).pack(fill='x', pady=(12, 0))
            self._hint(card, '例如 http://127.0.0.1:7890。留空使用系统网络设置。', pady=(6, 0))

        other = self._tab('组件更新')
        self.update_proxy = tk.StringVar(value=app.config.get('update_proxy', ''))
        card = self._card(other, 'yt-dlp 更新代理', '为检查和下载组件更新配置网络连接。')
        ttk.Entry(card, textvariable=self.update_proxy, width=20).pack(fill='x', pady=(12, 0))
        self._hint(card, '只用于从 PyPI 获取更新，独立于各视频站点的配置。留空使用系统网络设置。', pady=(8, 0))

        footer = ttk.Frame(self.dialog, padding=(24, 14), style='Settings.Card.TFrame')
        footer.grid(row=2, column=0, sticky='ew')
        footer.columnconfigure(0, weight=1)
        self.note_label = ttk.Label(footer, textvariable=self.note, style='Settings.Muted.TLabel', wraplength=500)
        self.note_label.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 10))
        ttk.Label(footer, text='更改后点击保存即可生效', style='Settings.Muted.TLabel').grid(row=1, column=0, sticky='w')
        actions = ttk.Frame(footer, style='Settings.Card.TFrame')
        actions.grid(row=1, column=1, sticky='e', padx=(12, 0))
        self.cancel_button = ttk.Button(actions, text='取消', command=self.close)
        self.cancel_button.pack(side='left', padx=(0, 8))
        self.save_button = ttk.Button(actions, text='保存配置', style='Accent.TButton', command=self.save)
        self.save_button.pack(side='left')
        footer.bind('<Configure>', lambda event: self.note_label.configure(wraplength=max(260, event.width - 48)))
        self.apply_theme()
        self._poll_job = self.dialog.after(100, self.poll)

    def apply_theme(self):
        """主窗口切换主题时同步已打开的设置窗口。"""
        if self._closed:
            return
        self.palette = dict(getattr(self.app, 'palette', None) or get_palette(getattr(self.app, 'theme_mode', 'light')))
        self._style()
        apply_native_theme(self.dialog, self.palette)

    def _style(self):
        palette = self.palette
        style = ttk.Style(self.dialog)
        style.configure('Settings.Page.TFrame', background=palette['bg'])
        style.configure('Settings.Card.TFrame', background=palette['card'])
        style.configure('Settings.Header.TFrame', background=palette['navy'])
        style.configure('Settings.HeaderTitle.TLabel', background=palette['navy'], foreground=palette.get('header_ink', '#FFFFFF'),
                        font=('Microsoft YaHei UI', 18, 'bold'))
        style.configure('Settings.HeaderNote.TLabel', background=palette['navy'], foreground=palette.get('header_muted', '#BDCCE0'),
                        font=('Microsoft YaHei UI', 9))
        style.configure('Settings.Section.TLabel', background=palette['card'], foreground=palette['ink'],
                        font=('Microsoft YaHei UI', 11, 'bold'))
        style.configure('Settings.Field.TLabel', background=palette['card'], foreground=palette['ink'])
        style.configure('Settings.Muted.TLabel', background=palette['card'], foreground=palette['muted'],
                        font=('Microsoft YaHei UI', 9))
        style.configure('Settings.TNotebook', background=palette['bg'], borderwidth=0, tabmargins=(0, 0, 0, 8))
        style.configure('Settings.TNotebook.Tab', padding=(17, 9), background=palette['soft'],
                        foreground=palette['muted'], font=('Microsoft YaHei UI', 10))
        style.map('Settings.TNotebook.Tab', background=[('selected', palette['card']), ('active', palette['border'])],
                  foreground=[('selected', palette['blue']), ('active', palette['ink'])])

    def _tab(self, title):
        tab = ttk.Frame(self.tabs, style='Settings.Page.TFrame')
        tab.rowconfigure(0, weight=1)
        tab.columnconfigure(0, weight=1)
        self.tabs.add(tab, text=title)
        canvas = tk.Canvas(tab, background=self.palette['bg'], borderwidth=0, highlightthickness=0, width=1, height=1)
        register_native(canvas, background='bg')
        canvas.grid(row=0, column=0, sticky='nsew')
        scrollbar = ttk.Scrollbar(tab, orient='vertical', command=canvas.yview)
        scrollbar.grid(row=0, column=1, sticky='ns', padx=(8, 0))
        canvas.configure(yscrollcommand=scrollbar.set)
        content = ttk.Frame(canvas, style='Settings.Page.TFrame')
        window = canvas.create_window((0, 0), window=content, anchor='nw')
        content.bind('<Configure>', lambda event, view=canvas: view.configure(scrollregion=view.bbox('all')))
        canvas.bind('<Configure>', lambda event, view=canvas, item=window: view.itemconfigure(item, width=event.width))
        self._scroll_views[str(tab)] = (canvas, content)
        return content

    def _card(self, parent, title, description):
        shell = tk.Frame(parent, background=self.palette['card'], highlightbackground=self.palette['border'], highlightthickness=1)
        register_native(shell, background='card', highlightbackground='border')
        shell.pack(fill='x', pady=(0, 12))
        card = ttk.Frame(shell, padding=18, style='Settings.Card.TFrame')
        card.pack(fill='both', expand=True)
        ttk.Label(card, text=title, style='Settings.Section.TLabel').pack(anchor='w')
        self._hint(card, description, pady=(5, 0))
        return card

    @staticmethod
    def _hint(parent, text, pady):
        label = ttk.Label(parent, text=text, style='Settings.Muted.TLabel', wraplength=560, justify='left')
        label.pack(fill='x', pady=pady)
        parent.bind('<Configure>', lambda event, item=label: item.configure(wraplength=max(120, event.width - 36)), add='+')
        return label

    def _wheel(self, event):
        selected = self._scroll_views.get(self.tabs.select())
        if not selected:
            return
        canvas, content = selected
        widget = event.widget
        while widget is not None and widget not in (canvas, content):
            widget = getattr(widget, 'master', None)
        if widget is None or content.winfo_height() <= canvas.winfo_height():
            return
        canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')
        return 'break'

    def _destroyed(self, event):
        if event.widget != self.dialog:
            return
        self._closed = True
        if self._poll_job is not None:
            try:
                self.dialog.after_cancel(self._poll_job)
            except tk.TclError:
                pass
            self._poll_job = None

    def read_file(self, site):
        if self.busy:
            return
        path = filedialog.askopenfilename(parent=self.dialog, filetypes=[('Cookie 文本', '*.txt'), ('全部文件', '*.*')])
        if path:
            self.start(site, lambda: import_cookies(path, self.root_dir / 'cookies', site))

    def read_browser(self, site, browser):
        profile = self.vars[site]['browser_profile'].get().strip() or None
        self.start(site, lambda: read_browser_cookies(browser, self.root_dir / 'cookies', site, profile))

    def start(self, site, operation):
        if self.busy:
            return
        self.busy = True
        self.note.set(f'正在读取 {SITES[site]} 的 Cookie，请稍候…')
        for button in self.buttons + [self.save_button, self.cancel_button]:
            button.configure(state='disabled')

        def worker():
            try:
                self.events.put(('ok', site, operation()))
            except Exception as exc:
                self.events.put(('error', site, str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        self._poll_job = None
        if self._closed:
            return
        try:
            kind, site, value = self.events.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            for button in self.buttons + [self.save_button, self.cancel_button]:
                button.configure(state='normal')
            if kind == 'ok':
                self.vars[site]['cookies'].set(value['path'])
                self.note.set(f"{SITES[site]} 已读取 {value['count']} 条有效 Cookie（来源 {value['source']}）。点击保存配置后使用。")
            else:
                self.note.set(value)
        self._poll_job = self.dialog.after(100, self.poll)

    def save(self):
        if self.busy:
            return
        config = copy.deepcopy(self.app.config)
        for site, values in self.vars.items():
            config.setdefault('sites', {}).setdefault(site, {}).update(
                {key: values[key].get().strip() for key in ('cookies', 'proxy')})
        config['update_proxy'] = self.update_proxy.get().strip()
        try:
            save_config(self.root_dir / 'settings.json', config)
        except OSError as exc:
            messagebox.showerror('保存失败', str(exc), parent=self.dialog)
            return
        self.app.config = config
        self.app.status.set('站点配置已保存。更新 Cookie 后请重新获取视频预览。')
        self.close()

    def close(self):
        if not self.busy:
            self.dialog.destroy()
