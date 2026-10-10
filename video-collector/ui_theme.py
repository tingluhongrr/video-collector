"""桌面窗口共用的亮色 / 暗色色彩与 ttk 控件主题。"""
import tkinter as tk
from tkinter import ttk

FONT = 'Microsoft YaHei UI'
# 旧常量代表亮色；切换时不修改模块全局变量。
BG = '#F3F5F9'
CARD = '#FFFFFF'
INK = '#17243B'
MUTED = '#738198'
BLUE = '#316CF4'
NAVY = '#14243D'
BORDER = '#E2E8F1'
SOFT = '#EFF4FD'
GREEN = '#16846B'
RED = '#C55261'

LIGHT = {
    'bg': BG, 'card': CARD, 'ink': INK, 'muted': MUTED, 'blue': BLUE,
    'navy': NAVY, 'border': BORDER, 'soft': SOFT, 'green': GREEN, 'red': RED,
    'input': '#F8FAFD', 'input_hint': '#9AA8BB',
    'selection': '#E9F0FF', 'selection_ink': '#2457BB',
    'header_ink': '#FFFFFF', 'header_muted': '#A5B6CE',
    'cover': '#14243D', 'cover_text': '#92A9CA', 'cover_circle': '#1E3658',
    'cover_outline': '#355375', 'cover_play': '#B3CBEB', 'cover_line': '#294463',
    'log_bg': '#101E33', 'log_fg': '#C2CEE0', 'log_selection': '#334E75',
    'button': '#EBF0F7', 'button_disabled': '#F0F3F8',
    'button_pressed': '#DCE5F3', 'button_hover': '#E0E8F5',
    'disabled_ink': '#9BA8BB', 'ghost_disabled_ink': '#A8B3C4',
    'accent': BLUE, 'accent_disabled': '#E2EAFB', 'accent_pressed': '#2055C9',
    'accent_hover': '#255FD9', 'accent_disabled_ink': '#7798D8',
    'header_button': '#253B5B', 'header_button_hover': '#304E73',
    'header_button_pressed': '#1D304C', 'header_button_disabled': '#20334D',
    'header_button_ink': '#E2ECFA', 'header_disabled_ink': '#7F92AE',
    'danger': '#FCF0F2', 'danger_hover': '#F9E0E6', 'danger_pressed': '#F4D2DC',
    'danger_disabled_ink': '#A7B2C3', 'combo_button': '#EEF3FA',
    'tree_heading': '#F5F7FB', 'tree_heading_hover': '#ECF1FA',
    'progress_trough': '#EAF0FA', 'scrollbar': '#DCE4F0',
    'scrollbar_hover': '#B9C9E2', 'scrollbar_pressed': '#A8BDDB',
    'tab': '#EFF3F9', 'tab_hover': '#E4ECFA', 'settings_tab': '#E9EEF7',
    'settings_header_muted': '#BDCCE0',
}
DARK = {
    'bg': '#111B2B', 'card': '#1B2A40', 'ink': '#E3EAF6', 'muted': '#9BAAC0',
    'blue': '#8DB1FF', 'navy': '#0D1726', 'border': '#34455F', 'soft': '#263B59',
    'green': '#60C5A6', 'red': '#EF94A0', 'input': '#142338', 'input_hint': '#8B9BB3',
    'selection': '#304E7C', 'selection_ink': '#E6EEFF',
    'header_ink': '#FFFFFF', 'header_muted': '#9AAFCB',
    'cover': '#142338', 'cover_text': '#9BAFCC', 'cover_circle': '#263E5E',
    'cover_outline': '#466589', 'cover_play': '#D0E0F8', 'cover_line': '#344F70',
    'log_bg': '#0D1726', 'log_fg': '#CCD7E7', 'log_selection': '#37547E',
    'button': '#2C3D57', 'button_disabled': '#233148',
    'button_pressed': '#3B5274', 'button_hover': '#354B6A',
    'disabled_ink': '#7788A2', 'ghost_disabled_ink': '#7788A2',
    'accent': '#386ACF', 'accent_disabled': '#253C61', 'accent_pressed': '#2D58B2',
    'accent_hover': '#4278DF', 'accent_disabled_ink': '#829DCB',
    'header_button': '#23364F', 'header_button_hover': '#304B6C',
    'header_button_pressed': '#1B2E48', 'header_button_disabled': '#1C2C41',
    'header_button_ink': '#E2ECFA', 'header_disabled_ink': '#7F92AE',
    'danger': '#442D41', 'danger_hover': '#573447', 'danger_pressed': '#65394C',
    'danger_disabled_ink': '#7788A2', 'combo_button': '#2B3E5B',
    'tree_heading': '#24344D', 'tree_heading_hover': '#304663',
    'progress_trough': '#2B3B54', 'scrollbar': '#40536F',
    'scrollbar_hover': '#566E90', 'scrollbar_pressed': '#6B86AC',
    'tab': '#26374F', 'tab_hover': '#344B6D', 'settings_tab': '#26374F',
    'settings_header_muted': '#AABDD6',
}


def get_palette(mode='light'):
    """返回独立的语义配色字典；未知配置值回退到亮色。"""
    return dict(DARK if mode == 'dark' else LIGHT)


def register_native(widget, **option_to_role):
    """记录 Tk 原生控件的角色，例如 background='card'。"""
    roles = getattr(widget, '_theme_roles', {}).copy()
    roles.update(option_to_role)
    widget._theme_roles = roles
    return widget


def apply_native_theme(parent, palette):
    """递归更新已注册原生控件，包括仍打开的子窗口，不影响 ttk。"""
    try:
        if not parent.winfo_exists():
            return
        roles = getattr(parent, '_theme_roles', {})
        if roles and not isinstance(parent, ttk.Widget):
            parent.configure(**{option: palette[role] for option, role in roles.items()})
        for child in parent.winfo_children():
            apply_native_theme(child, palette)
    except tk.TclError:
        # 子窗口可能在切换时刚好关闭。
        return


def _update_combobox_popdowns(root, palette):
    """同步已经创建的 Tcl 下拉列表，option_add 仅影响新建列表。"""
    pending = [str(root)]
    while pending:
        path = pending.pop()
        try:
            pending.extend(root.tk.splitlist(root.tk.call('winfo', 'children', path)))
            if '.popdown.' in path and root.tk.call('winfo', 'class', path) == 'Listbox':
                root.tk.call(path, 'configure', '-background', palette['card'],
                             '-foreground', palette['ink'],
                             '-selectbackground', palette['selection'],
                             '-selectforeground', palette['selection_ink'])
        except tk.TclError:
            continue


def apply_theme(root, mode='light'):
    """保持字号和布局，应用完整主题并返回 ttk.Style。"""
    p = get_palette(mode)
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', font=(FONT, 9), foreground=p['ink'], background=p['card'],
                    bordercolor=p['border'], lightcolor=p['border'], darkcolor=p['border'],
                    troughcolor=p['progress_trough'], selectbackground=p['selection'],
                    selectforeground=p['selection_ink'])
    style.map('.', background=[('disabled', p['card']), ('active', p['card'])],
              foreground=[('disabled', p['disabled_ink'])],
              selectbackground=[('!focus', p['selection'])],
              selectforeground=[('!focus', p['selection_ink'])])
    for name, color in [('Page', p['bg']), ('Card', p['card']), ('Header', p['navy']), ('Soft', p['soft'])]:
        style.configure(name + '.TFrame', background=color, borderwidth=0)
    style.configure('TLabel', background=p['card'], foreground=p['ink'])
    for name, background, color in [('Muted', p['card'], p['muted']), ('PageMuted', p['bg'], p['muted']),
                                     ('HeaderMuted', p['navy'], p['header_muted']), ('Header', p['navy'], p['header_ink'])]:
        style.configure(name + '.TLabel', background=background, foreground=color, font=(FONT, 9))
    style.configure('Hero.TLabel', background=p['navy'], foreground=p['header_ink'], font=(FONT, 17, 'bold'))
    style.configure('Section.TLabel', background=p['card'], foreground=p['ink'], font=(FONT, 11, 'bold'))
    style.configure('Title.TLabel', background=p['card'], foreground=p['ink'], font=(FONT, 15, 'bold'))
    style.configure('Badge.TLabel', background=p['soft'], foreground=p['blue'], font=(FONT, 8, 'bold'), padding=(8, 4))
    style.configure('Step.TLabel', background=p['soft'], foreground=p['blue'], font=('Segoe UI', 10, 'bold'), padding=(7, 3))
    style.configure('TButton', background=p['button'], foreground=p['ink'], borderwidth=0, padding=(12, 8), font=(FONT, 9))
    style.map('TButton', background=[('disabled', p['button_disabled']), ('pressed', p['button_pressed']), ('active', p['button_hover'])],
              foreground=[('disabled', p['disabled_ink']), ('!disabled', p['ink'])])
    style.configure('Accent.TButton', background=p['accent'], foreground='white', font=(FONT, 9, 'bold'))
    style.map('Accent.TButton', background=[('disabled', p['accent_disabled']), ('pressed', p['accent_pressed']), ('active', p['accent_hover'])],
              foreground=[('disabled', p['accent_disabled_ink']), ('!disabled', 'white')])
    style.configure('Ghost.TButton', background=p['card'], foreground=p['muted'], padding=(8, 8))
    style.map('Ghost.TButton', background=[('disabled', p['card']), ('pressed', p['soft']), ('active', p['soft'])],
              foreground=[('disabled', p['ghost_disabled_ink']), ('active', p['blue']), ('!disabled', p['muted'])])
    style.configure('Header.TButton', background=p['header_button'], foreground=p['header_button_ink'], padding=(12, 8))
    style.map('Header.TButton', background=[('disabled', p['header_button_disabled']), ('pressed', p['header_button_pressed']), ('active', p['header_button_hover'])],
              foreground=[('disabled', p['header_disabled_ink']), ('!disabled', p['header_button_ink'])])
    style.configure('Danger.TButton', foreground=p['red'], background=p['danger'])
    style.map('Danger.TButton', background=[('disabled', p['bg']), ('pressed', p['danger_pressed']), ('active', p['danger_hover'])],
              foreground=[('disabled', p['danger_disabled_ink']), ('!disabled', p['red'])])
    style.configure('TEntry', fieldbackground=p['input'], foreground=p['ink'], bordercolor=p['border'], lightcolor=p['border'],
                    darkcolor=p['border'], padding=(9, 7), insertcolor=p['ink'], selectbackground=p['selection'], selectforeground=p['selection_ink'])
    style.map('TEntry', bordercolor=[('focus', p['blue'])], lightcolor=[('focus', p['blue']), ('!focus', p['border'])],
              fieldbackground=[('disabled', p['bg']), ('readonly', p['input'])],
              foreground=[('disabled', p['disabled_ink']), ('!disabled', p['ink'])])
    style.configure('TCombobox', fieldbackground=p['input'], foreground=p['ink'], background=p['combo_button'], bordercolor=p['border'],
                    lightcolor=p['border'], darkcolor=p['border'], arrowcolor=p['muted'], padding=(8, 6), insertcolor=p['ink'],
                    selectbackground=p['selection'], selectforeground=p['selection_ink'])
    style.map('TCombobox', fieldbackground=[('disabled', p['bg']), ('readonly', p['input']), ('!disabled', p['input'])],
              background=[('disabled', p['bg']), ('active', p['soft']), ('!disabled', p['combo_button'])],
              foreground=[('disabled', p['input_hint']), ('!disabled', p['ink'])],
              arrowcolor=[('disabled', p['disabled_ink']), ('!disabled', p['muted'])], bordercolor=[('focus', p['blue'])])
    style.configure('Treeview', rowheight=34, fieldbackground=p['card'], background=p['card'], foreground=p['ink'], borderwidth=0, font=(FONT, 9))
    style.layout('Treeview', [('Treeview.treearea', {'sticky': 'nswe'})])
    style.configure('Treeview.Heading', background=p['tree_heading'], foreground=p['muted'], borderwidth=0, padding=(10, 8), font=(FONT, 8, 'bold'))
    style.map('Treeview.Heading', background=[('active', p['tree_heading_hover'])], foreground=[('!disabled', p['muted'])])
    style.map('Treeview', background=[('selected', p['selection'])], foreground=[('selected', p['selection_ink'])])
    style.configure('TRadiobutton', background=p['card'], foreground=p['ink'], font=(FONT, 9), padding=(0, 4),
                    indicatorbackground=p['input'], indicatorforeground=p['ink'], bordercolor=p['border'], lightcolor=p['border'], darkcolor=p['border'])
    style.map('TRadiobutton', background=[('active', p['card'])], foreground=[('disabled', p['disabled_ink']), ('!disabled', p['ink'])],
              indicatorbackground=[('disabled', p['bg']), ('!disabled', p['input'])],
              indicatorforeground=[('disabled', p['disabled_ink']), ('selected', p['blue'])])
    style.configure('TCheckbutton', background=p['card'], foreground=p['muted'], font=(FONT, 9), padding=0,
                    indicatorbackground=p['input'], indicatorforeground=p['ink'], bordercolor=p['border'],
                    lightcolor=p['border'], darkcolor=p['border'])
    style.map('TCheckbutton', background=[('active', p['card'])],
              foreground=[('disabled', p['disabled_ink']), ('active', p['blue']), ('!disabled', p['muted'])],
              indicatorbackground=[('disabled', p['bg']), ('!disabled', p['input'])],
              indicatorforeground=[('disabled', p['disabled_ink']), ('selected', p['blue'])])
    style.configure('Blue.Horizontal.TProgressbar', background=p['accent'], troughcolor=p['progress_trough'], borderwidth=0,
                    bordercolor=p['progress_trough'], troughrelief='flat', lightcolor=p['accent'], darkcolor=p['accent'], thickness=7)
    for name in ('Vertical.TScrollbar', 'Horizontal.TScrollbar'):
        style.configure(name, background=p['scrollbar'], troughcolor=p['card'], borderwidth=0, bordercolor=p['card'],
                        lightcolor=p['card'], darkcolor=p['card'], arrowsize=11, arrowcolor=p['muted'])
        style.map(name, background=[('pressed', p['scrollbar_pressed']), ('active', p['scrollbar_hover'])],
                  arrowcolor=[('disabled', p['disabled_ink']), ('!disabled', p['muted'])])
    style.configure('TSeparator', background=p['border'])
    style.configure('TNotebook', background=p['card'], borderwidth=0, tabmargins=(0, 0, 0, 6))
    style.configure('TNotebook.Tab', background=p['tab'], foreground=p['muted'], padding=(14, 9), borderwidth=0)
    style.map('TNotebook.Tab', background=[('disabled', p['bg']), ('selected', p['accent']), ('active', p['tab_hover'])],
              foreground=[('disabled', p['disabled_ink']), ('selected', 'white'), ('!disabled', p['muted'])],
              lightcolor=[('selected', p['border']), ('!selected', p['border'])])
    style.configure('ComboboxPopdownFrame', bordercolor=p['border'], background=p['card'])
    root.option_add('*TCombobox*Listbox.font', (FONT, 9))
    root.option_add('*TCombobox*Listbox.background', p['card'])
    root.option_add('*TCombobox*Listbox.foreground', p['ink'])
    root.option_add('*TCombobox*Listbox.selectBackground', p['selection'])
    root.option_add('*TCombobox*Listbox.selectForeground', p['selection_ink'])
    _update_combobox_popdowns(root, p)
    return style
