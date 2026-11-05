"""Apple Music inspired desktop shell; keeps the verified pipeline UI controller."""
import json
import os
import queue
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

from music_app import MusicApp
from music_catalog import artwork_png, item_url, lookup
from music_core import ROOT, Settings, parse_links

RED = "#fa243c"
INK = "#1d1d1f"
MUTED = "#86868b"
SIDE = "#f5f5f7"
BORDER = "#e5e5ea"


class AppleMusicApp(MusicApp):
    def __init__(self, root):
        self.catalog_events = queue.Queue()
        self.query = tk.StringVar(root)
        self.search_type = tk.StringVar(root, value="专辑")
        self.catalog_country = tk.StringVar(root, value="gb")
        self.catalog_note = tk.StringVar(root, value="搜索歌曲、艺人或专辑，或粘贴 Apple Music 链接。")
        self.catalog_items = {}
        self.current_item = None
        self.current_url = ""
        self.catalog_mode = "search"
        self.catalog_generation = 0
        self.art_generation = 0
        self.art_image = None
        super().__init__(root)
        self.root.title("Music 工作台 v0.2 Mac 移植预览 · 标签与歌词")
        # The .app icon is owned by macOS, not Tk iconbitmap.
        self.root.minsize(1040, 700)
        self.root.after(500, self.load_recent)

    def _style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", font=("PingFang SC", 10), background="white", foreground=INK)
        style.configure("TFrame", background="white")
        style.configure("TLabel", background="white")
        style.configure("TButton", background="#f0f0f3", borderwidth=0, padding=(13, 8))
        style.map("TButton", background=[("active", "#e7e7eb")])
        style.configure("Accent.TButton", background=RED, foreground="white", font=("PingFang SC", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#e82038"), ("disabled", "#f4aab4")], foreground=[("disabled", "white")])
        style.configure("Muted.TLabel", foreground=MUTED, background="white", font=("PingFang SC", 9))
        style.configure("Heading.TLabel", font=("PingFang SC", 25, "bold"))
        style.configure("Treeview", background="white", fieldbackground="white", rowheight=38, borderwidth=0, font=("PingFang SC", 10))
        style.configure("Treeview.Heading", background="white", foreground=MUTED, font=("PingFang SC", 9), borderwidth=0, padding=(8, 9))
        style.map("Treeview", background=[("selected", "#fde9ed")], foreground=[("selected", "#b9152e")])
        style.configure("TProgressbar", background=RED, troughcolor="#f0f0f3", borderwidth=0)
        style.configure("TEntry", padding=7, fieldbackground="#f5f5f7", bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
        style.configure("TRadiobutton", background="white", padding=(0, 3))
        style.configure("TCombobox", padding=5)

    def _build(self):
        self.root.configure(bg="white")
        shell = tk.Frame(self.root, bg="white")
        shell.pack(fill="both", expand=True)
        sidebar = tk.Frame(shell, bg=SIDE, width=202, highlightbackground=BORDER, highlightthickness=1)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        brand = tk.Frame(sidebar, bg=SIDE)
        brand.pack(fill="x", padx=22, pady=(25, 26))
        tk.Label(brand, text="♫", font=("Apple Symbols", 29), fg=RED, bg=SIDE).pack(side="left")
        tk.Label(brand, text="Music", font=("Helvetica Neue", 24, "bold"), fg=INK, bg=SIDE).pack(side="left", padx=5)
        tk.Label(sidebar, text="音乐工作台", bg=SIDE, fg=MUTED, font=("PingFang SC", 9)).pack(anchor="w", padx=24, pady=(0, 8))
        self.nav_buttons = {}
        for key, text in (("discover", "⌕   搜索发现"), ("queue", "↓   下载与任务"), ("library", "♫   我的音乐库"), ("tags", "✎   标签与歌词"), ("convert", "⇄   本地转码"), ("settings", "⚙   设置")):
            button = tk.Button(sidebar, text=text, anchor="w", relief="flat", borderwidth=0,
                               bg=SIDE, fg=INK, activebackground="#e8e8ed", activeforeground=RED,
                               font=("PingFang SC", 11), padx=17, pady=10,
                               cursor="hand2", command=lambda k=key: self.show_page(k))
            button.pack(fill="x", padx=11, pady=2)
            self.nav_buttons[key] = button
        service_box = tk.Frame(sidebar, bg=SIDE)
        service_box.pack(side="bottom", fill="x", padx=18, pady=20)
        tk.Label(service_box, text="AMDL × fre:ac", font=("Helvetica Neue", 10, "bold"), fg=INK, bg=SIDE).pack(anchor="w", pady=(0, 9))
        tk.Label(service_box, textvariable=self.service, wraplength=165, justify="left", bg=SIDE, fg=MUTED,
                 font=("PingFang SC", 9)).pack(anchor="w")
        self.service_button = ttk.Button(service_box, text="打开解密服务", command=self.open_service)
        self.service_button.pack(fill="x", pady=(10, 5))
        ttk.Button(service_box, text="刷新服务状态", command=self.refresh_service).pack(fill="x")
        tk.Label(service_box, text="下载结束可关闭服务窗口", bg=SIDE, fg=MUTED, font=("PingFang SC", 8)).pack(pady=(9, 0))

        main = ttk.Frame(shell)
        main.pack(side="left", fill="both", expand=True)
        search_bar = ttk.Frame(main, padding=(28, 19, 28, 15))
        search_bar.pack(fill="x")
        self.search_entry = ttk.Entry(search_bar, textvariable=self.query, font=("PingFang SC", 11))
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.search_entry.bind("<Return>", lambda event: self.search_catalog())
        # Entry placeholders remain separate from actual search text.
        self.search_hint = ttk.Label(main, text="搜索歌曲、艺人、专辑，或粘贴 Apple Music 链接", style="Muted.TLabel")
        self.search_hint.pack(anchor="w", padx=29, pady=(0, 10))
        ttk.Combobox(search_bar, textvariable=self.search_type, values=("专辑", "歌曲"), width=5, state="readonly").pack(side="left", padx=4)
        ttk.Combobox(search_bar, textvariable=self.catalog_country, values=("gb", "us", "cn", "jp", "hk", "tw"), width=4, state="readonly").pack(side="left", padx=4)
        self.search_button = ttk.Button(search_bar, text="搜索 / 解析", command=self.search_catalog)
        self.search_button.pack(side="left", padx=(8, 0))
        tk.Frame(main, bg=BORDER, height=1).pack(fill="x")

        bottom = ttk.Frame(main, padding=(27, 13, 27, 12))
        self.workflow_footer = bottom
        bottom.pack(side="bottom", fill="x")
        options = ttk.Frame(bottom)
        options.pack(fill="x")
        ttk.Label(options, text="输出", style="Muted.TLabel").pack(side="left", padx=(0, 12))
        self.preset_buttons = []
        for text, value in (("FLAC + AAC", "both"), ("FLAC", "flac"), ("AAC-LC 256k", "aac"), ("仅 ALAC", "none")):
            button = ttk.Radiobutton(options, text=text, variable=self.mode, value=value)
            button.pack(side="left", padx=(0, 15))
            self.preset_buttons.append(button)
        ttk.Button(options, text="打开音乐库", command=self.open_output).pack(side="right")
        self.phase_label = ttk.Label(bottom, textvariable=self.phase, wraplength=750, style="Muted.TLabel")
        self.phase_label.pack(anchor="w", pady=(11, 6))
        progress_row = ttk.Frame(bottom)
        progress_row.pack(fill="x")
        self.progress = ttk.Progressbar(progress_row, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=(0, 12))
        self.stop_button = ttk.Button(progress_row, text="完成当前曲目后停止", command=self.request_stop, state="disabled")
        self.stop_button.pack(side="right")
        self.footer_separator = tk.Frame(main, bg=BORDER, height=1)
        self.footer_separator.pack(side="bottom", fill="x")

        body = ttk.Frame(main)
        self.body_container = body
        body.pack(fill="both", expand=True)
        self.pages = {}
        for key in self.nav_buttons:
            page = ttk.Frame(body, padding=(28, 20, 28, 12))
            self.pages[key] = page
        self.build_discover(self.pages["discover"])
        self.build_queue(self.pages["queue"])
        self.build_convert(self.pages["convert"])
        self.build_settings(self.pages["settings"])
        self.build_library(self.pages["library"])
        from music_tags_ui import TagPanel
        self.tag_panel = TagPanel(self.pages["tags"], self)
        self.tag_panel.pack(fill="both", expand=True)
        self.show_page("discover")

    def heading(self, parent, text, subtitle=""):
        ttk.Label(parent, text=text, style="Heading.TLabel").pack(anchor="w")
        if subtitle:
            ttk.Label(parent, text=subtitle, style="Muted.TLabel").pack(anchor="w", pady=(6, 18))

    def build_discover(self, page):
        self.heading(page, "搜索发现", "从喜欢的专辑开始，下载无损原音，整理你的音乐库。")
        hero = ttk.Frame(page)
        hero.pack(fill="x", pady=(0, 17))
        cover_box = tk.Frame(hero, width=174, height=174, bg="#fff0f3")
        cover_box.pack(side="left", anchor="n", padx=(0, 22))
        cover_box.pack_propagate(False)
        self.cover = tk.Label(cover_box, text="♫", bg="#fff0f3", fg=RED, font=("Apple Symbols", 66))
        self.cover.pack(fill="both", expand=True)
        album = ttk.Frame(hero)
        album.pack(side="left", fill="both", expand=True)
        self.album_kind = ttk.Label(album, text="APPLE MUSIC", foreground=RED, font=("Helvetica Neue", 9, "bold"))
        self.album_kind.pack(anchor="w", pady=(3, 6))
        self.album_title = ttk.Label(album, text="发现下一张好专辑", font=("PingFang SC", 20, "bold"), wraplength=600)
        self.album_title.pack(anchor="w", fill="x")
        album.bind("<Configure>", lambda event: self.album_title.configure(wraplength=max(250, event.width - 10)))
        self.album_artist = ttk.Label(album, text="输入歌名、艺人名，或粘贴链接", foreground=RED, font=("PingFang SC", 12))
        self.album_artist.pack(anchor="w", pady=(6, 3))
        self.album_detail = ttk.Label(album, text="ALAC 无损原音 · FLAC 归档 · AAC 便携副本", style="Muted.TLabel")
        self.album_detail.pack(anchor="w", pady=(0, 10))
        actions = ttk.Frame(album)
        actions.pack(anchor="w")
        self.album_download_button = ttk.Button(actions, text="↓ 下载整张专辑", style="Accent.TButton", command=self.download_album, state="disabled")
        self.album_download_button.pack(side="left", padx=(0, 8))
        self.track_download_button = ttk.Button(actions, text="下载选中曲目", command=self.download_tracks, state="disabled")
        self.track_download_button.pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="在 Apple Music 中打开 ↗", command=self.open_apple).pack(side="left")
        ttk.Label(page, textvariable=self.catalog_note, style="Muted.TLabel", wraplength=900).pack(anchor="w", pady=(0, 6))
        frame = ttk.Frame(page)
        frame.pack(fill="both", expand=True)
        self.catalog_tree = ttk.Treeview(frame, columns=("number", "title", "artist", "album", "time"), show="headings", selectmode="extended")
        for key, text, width in (("number", "#", 40), ("title", "名称", 310), ("artist", "艺人", 160), ("album", "专辑", 180), ("time", "时长", 65)):
            self.catalog_tree.heading(key, text=text)
            self.catalog_tree.column(key, width=width, minwidth=35, stretch=key in ("title", "album"))
        self.catalog_tree.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.catalog_tree.yview)
        scroll.pack(side="right", fill="y")
        self.catalog_tree.configure(yscrollcommand=scroll.set)
        self.catalog_tree.bind("<<TreeviewSelect>>", self.select_catalog)
        self.catalog_tree.bind("<Double-1>", self.expand_album)
        ttk.Label(page, text="双击专辑查看曲目 · Ctrl / Shift 多选歌曲 · 目录来自 Apple 的公开搜索接口", style="Muted.TLabel").pack(anchor="w", pady=(9, 0))

    def build_queue(self, page):
        self.heading(page, "下载与任务", "批量粘贴链接，或从搜索结果选择专辑和曲目。")
        self.links = scrolledtext.ScrolledText(page, height=3, font=("Helvetica Neue", 10), wrap="word", relief="solid", borderwidth=1, padx=9, pady=8)
        self.links.pack(fill="x")
        row = ttk.Frame(page)
        row.pack(fill="x", pady=(10, 12))
        self.download_button = ttk.Button(row, text="↓ 开始下载并处理", style="Accent.TButton", command=self.start_download)
        self.download_button.pack(side="left")
        self.tag_results_button = ttk.Button(row, text="本次成品自动匹配", command=self.open_tag_results)
        self.tag_results_button.pack(side="left", padx=9)
        ttk.Button(row, text="查看日志和报告", command=lambda: self.open_folder(ROOT / "logs")).pack(side="right")
        frame = ttk.Frame(page)
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(frame, columns=("file", "preset", "status", "detail"), show="headings", height=4)
        for key, text, width in (("file", "曲目", 260), ("preset", "格式", 70), ("status", "状态", 120), ("detail", "校验 / 说明", 300)):
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width, minwidth=50)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.tag_configure("failed", foreground="#b9152e")
        self.tree.tag_configure("ok", foreground="#26734a")
        self.tree.bind("<Double-1>", self.show_result)
        self.row_results = {}
        self.log_view = scrolledtext.ScrolledText(page, height=5, wrap="word", font=("PingFang SC", 9), background="#f5f5f7", foreground="#5b5b63", relief="flat", padx=9, pady=7, state="disabled")
        self.log_view.pack(fill="x", pady=(12, 0))

    def build_convert(self, page):
        self.heading(page, "本地转码", "把已有无损音乐，整理成适合收藏和随身聆听的格式。")
        row = ttk.Frame(page)
        row.pack(fill="x", pady=8)
        ttk.Radiobutton(row, text="整个文件夹（含子目录）", variable=self.source_mode, value="folder").pack(side="left", padx=(0, 22))
        ttk.Radiobutton(row, text="指定音频文件", variable=self.source_mode, value="files").pack(side="left")
        self.source_entry = ttk.Entry(page, textvariable=self.source_folder)
        self.source_entry.pack(fill="x", pady=(8, 13))
        row = ttk.Frame(page)
        row.pack(fill="x")
        ttk.Button(row, text="选择文件夹", command=self.choose_source_folder).pack(side="left", padx=(0, 8))
        ttk.Button(row, text="选择音频文件…", command=self.choose_files).pack(side="left", padx=(0, 12))
        self.selection_label = ttk.Label(row, text="尚未选择单独文件", style="Muted.TLabel")
        self.selection_label.pack(side="left")
        self.convert_button = ttk.Button(row, text="开始转码", style="Accent.TButton", command=self.start_convert)
        self.convert_button.pack(side="right")
        cards = ttk.Frame(page)
        cards.pack(fill="x", pady=(33, 22))
        for title, body in (("FLAC", "无损归档\n压缩等级 6\n保留采样率与声道\n与源 PCM 一致性校验"), ("AAC-LC", "便携副本\n立体声 256 kbps\n使用 LC profile\n全曲音频解码校验")):
            card = tk.Frame(cards, bg=SIDE, padx=24, pady=20)
            card.pack(side="left", fill="both", expand=True, padx=(0, 15))
            tk.Label(card, text=title, font=("Helvetica Neue", 24, "bold"), fg=RED, bg=SIDE).pack(anchor="w")
            tk.Label(card, text=body, font=("PingFang SC", 11), fg=INK, bg=SIDE, justify="left").pack(anchor="w", pady=(9, 0))
        ttk.Label(page, text="保留原目录、文件名、内嵌封面与标签；LRC 随成品复制。\n原文件保留，已有成品核验后跳过，有损输入不再转码。", style="Muted.TLabel").pack(anchor="w")

    def build_settings(self, page):
        self.heading(page, "设置", "AMDL、fre:ac 与标签组件已内置；外部 MusicTag 可选。")
        grid = ttk.Frame(page)
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)
        for index, (name, key) in enumerate((("AMDL 安装目录", "amdl_root"), ("freaccmd", "freac"), ("外部标签应用（可选）", "musictag"), ("音乐库位置", "output"))):
            ttk.Label(grid, text=name).grid(row=index, column=0, sticky="w", padx=(0, 15), pady=10)
            ttk.Entry(grid, textvariable=self.vars[key]).grid(row=index, column=1, sticky="ew", pady=10)
            ttk.Button(grid, text="浏览…", command=lambda k=key: self.browse_setting(k)).grid(row=index, column=2, padx=(10, 0))
        row = ttk.Frame(page)
        row.pack(fill="x", pady=15)
        ttk.Label(row, text="并行曲目数").pack(side="left")
        ttk.Spinbox(row, from_=1, to=10, width=4, textvariable=self.vars["workers"]).pack(side="left", padx=(10, 24))
        ttk.Label(row, text="AMDL 商店地区").pack(side="left")
        ttk.Entry(row, width=5, textvariable=self.vars["storefront"]).pack(side="left", padx=10)
        self.save_button = ttk.Button(row, text="保存并检查路径", command=self.save_settings, style="Accent.TButton")
        self.save_button.pack(side="right")
        ttk.Label(page, text="搜索栏地区只影响目录检索；实际下载权限由账号决定。\n配置位于用户 Library/Application Support；解密服务使用独立 Docker 容器。", style="Muted.TLabel").pack(anchor="w", pady=15)
        ttk.Label(page, text="当前音乐库", font=("PingFang SC", 12, "bold")).pack(anchor="w", pady=(20, 8))
        ttk.Label(page, textvariable=self.vars["output"], style="Muted.TLabel").pack(anchor="w")

    def build_library(self, page):
        self.heading(page, "我的音乐库", "下载原音、无损归档和便携副本，各有自己的位置。")
        row = ttk.Frame(page)
        row.pack(fill="x", pady=(0, 22))
        for name, folder in (("ALAC 原音", "ALAC"), ("FLAC 归档", "FLAC"), ("AAC 便携副本", "AAC-LC 256k")):
            ttk.Button(row, text=name + " ↗", command=lambda f=folder: self.open_folder(Path(self.vars["output"].get()) / f)).pack(side="left", padx=(0, 12))
        ttk.Label(page, text="最近任务", font=("PingFang SC", 15, "bold")).pack(anchor="w", pady=(0, 10))
        self.library_tree = ttk.Treeview(page, columns=("date", "name", "status"), show="headings")
        for key, text, width in (("date", "任务时间", 150), ("name", "曲目 / 下载", 480), ("status", "结果", 130)):
            self.library_tree.heading(key, text=text)
            self.library_tree.column(key, width=width)
        self.library_tree.pack(fill="both", expand=True)
        ttk.Button(page, text="刷新最近任务", command=self.load_recent).pack(anchor="e", pady=(12, 0))

    def show_page(self, key):
        if key == "tags":
            self.workflow_footer.pack_forget()
            self.footer_separator.pack_forget()
        elif not self.workflow_footer.winfo_manager():
            self.workflow_footer.pack(side="bottom", fill="x", before=self.body_container)
            self.footer_separator.pack(side="bottom", fill="x", before=self.body_container)
        for name, page in self.pages.items():
            page.pack_forget()
            self.nav_buttons[name].configure(bg="#fce3e8" if name == key else SIDE, fg=RED if name == key else INK)
        self.pages[key].pack(fill="both", expand=True)
        if key == "library":
            self.load_recent()

    def search_catalog(self):
        query = self.query.get().strip()
        if not query:
            self.search_entry.focus_set()
            return
        # Accept a Markdown link pasted from chat as well as an ordinary URL.
        if query.startswith("[") and "](" in query and query.endswith(")"):
            query = query.rsplit("](", 1)[1][:-1]
        self.catalog_generation += 1
        generation = self.catalog_generation
        country = self.catalog_country.get()
        entity = "album" if self.search_type.get() == "专辑" else "song"
        self.catalog_note.set("正在查询目录…")
        self.album_download_button.configure(state="disabled")
        self.track_download_button.configure(state="disabled")
        self.show_page("discover")

        def worker():
            try:
                result = lookup(query, country, entity)
                self.catalog_events.put(("catalog", generation, result))
            except Exception as exc:
                self.catalog_events.put(("catalog_error", generation, (str(exc), query)))
        threading.Thread(target=worker, daemon=True).start()

    def render_catalog(self, result):
        self.catalog_mode = result["mode"]
        self.current_url = result["url"]
        self.catalog_country.set(result["country"])
        self.catalog_tree.delete(*self.catalog_tree.get_children())
        self.catalog_items.clear()
        items = result["items"]
        collection = next((item for item in items if item.get("wrapperType") == "collection"), None)
        tracks = [item for item in items if item.get("kind") == "song"]
        visible = tracks if self.catalog_mode in ("album", "song") else items
        for index, item in enumerate(visible):
            is_track = item.get("kind") == "song"
            duration = item.get("trackTimeMillis", 0) // 1000
            row = self.catalog_tree.insert("", "end", values=(item.get("trackNumber", index + 1) if is_track else "专辑",
                item.get("trackName") if is_track else item.get("collectionName", ""), item.get("artistName", ""),
                item.get("collectionName", "") if is_track else f"{item.get('trackCount', '—')} 首歌曲",
                f"{duration // 60}:{duration % 60:02}" if duration else "—"))
            self.catalog_items[row] = item
        if self.catalog_mode == "playlist":
            self.current_item = None
            self.art_generation += 1
            self.cover.configure(image="", text="♫")
            self.album_kind.configure(text="歌单")
            self.album_title.configure(text="Apple Music 歌单")
            self.album_artist.configure(text="使用链接直接下载")
            self.album_detail.configure(text="此公开目录不提供歌单曲目；下载引擎仍可处理链接。")
            self.album_download_button.configure(text="↓ 下载歌单", state="normal" if not self.activity_busy() else "disabled")
            self.track_download_button.configure(state="disabled")
            self.catalog_note.set("已识别歌单链接。")
            return
        if not items:
            self.catalog_note.set("这个地区的公开目录没有返回结果；可换地区检索，或到「下载与任务」直接使用链接。")
            self.current_item = None
            self.art_generation += 1
            self.cover.configure(image="", text="♫")
            self.album_title.configure(text="未找到目录结果")
            self.album_artist.configure(text="试试其他地区或关键词")
            self.album_detail.configure(text="也可使用原链接直接下载")
            self.album_download_button.configure(state="disabled")
            self.track_download_button.configure(state="disabled")
            return
        self.set_hero(collection or visible[0])
        if self.catalog_mode == "song" and visible:
            first = self.catalog_tree.get_children()[0]
            self.catalog_tree.selection_set(first)
        self.catalog_note.set(f"{len(visible)} {'首歌曲' if tracks and self.catalog_mode != 'search' else '项结果'} · {result['country'].upper()} 目录 · 实际下载音质以引擎取流结果为准")

    def set_hero(self, item):
        self.current_item = item
        is_track = item.get("kind") == "song"
        self.album_kind.configure(text="歌曲" if is_track else "专辑")
        self.album_title.configure(text=item.get("trackName") if is_track else item.get("collectionName", ""))
        self.album_artist.configure(text=item.get("artistName", ""))
        year = item.get("releaseDate", "")[:4]
        detail = " · ".join(str(value) for value in (year, item.get("primaryGenreName"), f"{item['trackCount']} 首歌曲" if item.get("trackCount") else None) if value)
        self.album_detail.configure(text=detail)
        self.album_download_button.configure(text="↓ 下载整张专辑", state="normal" if item.get("collectionId") and not self.activity_busy() else "disabled")
        self.track_download_button.configure(state="normal" if is_track and not self.activity_busy() else "disabled")
        self.art_generation += 1
        generation = self.art_generation
        self.cover.configure(image="", text="♫")
        self.art_image = None
        from mac_runtime import tool
        ffmpeg = tool("ffmpeg")
        def worker():
            try:
                data = artwork_png(item, ffmpeg, 174)
                self.catalog_events.put(("art", generation, data))
            except Exception:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def select_catalog(self, _event=None):
        selected = self.catalog_tree.selection()
        if selected:
            item = self.catalog_items.get(selected[0])
            if item and self.catalog_mode == "search":
                self.set_hero(item)
            self.track_download_button.configure(state="normal" if any(self.catalog_items.get(row, {}).get("kind") == "song" for row in selected) and not self.activity_busy() else "disabled")

    def expand_album(self, _event=None):
        selected = self.catalog_tree.selection()
        if selected:
            item = self.catalog_items.get(selected[0], {})
            if item.get("collectionId"):
                self.query.set(item_url(item, self.catalog_country.get()))
                self.search_catalog()

    def download_album(self):
        if self.catalog_mode == "playlist" and self.current_url:
            links = [self.current_url]
        elif self.current_item:
            links = [item_url(self.current_item, self.catalog_country.get())]
        else:
            return
        self.queue_links(links)

    def download_tracks(self):
        items = [self.catalog_items[row] for row in self.catalog_tree.selection() if self.catalog_items[row].get("kind") == "song"]
        if items:
            self.queue_links([item_url(item, self.catalog_country.get(), track=True) for item in items])

    def queue_links(self, links):
        if self.activity_busy():
            self.show_page("queue")
            return
        self.links.delete("1.0", "end")
        self.links.insert("1.0", "\n".join(links))
        self.start_download()

    def open_apple(self):
        try:
            url = self.current_url or (item_url(self.current_item, self.catalog_country.get()) if self.current_item else "https://music.apple.com/")
            webbrowser.open(url)
        except Exception as exc:
            messagebox.showerror("Apple Music", str(exc), parent=self.root)

    def start(self, settings, work, downloading=False):
        if getattr(self, "tagging_busy", False):
            self.phase.set("标签任务正在进行，请等待完成后再下载或转码")
            return
        super().start(settings, work, downloading)
        self.show_page("queue")

    def set_controls(self, enabled):
        super().set_controls(enabled)
        self.album_download_button.configure(state="normal" if enabled and (self.current_item or self.catalog_mode == "playlist") else "disabled")
        self.select_catalog()

    def activity_busy(self):
        return self.busy or getattr(self, "tagging_busy", False)

    def open_tag_results(self):
        self.show_page("tags")
        self.tag_panel.load_recent()

    def close(self):
        panel = getattr(self, "tag_panel", None)
        if panel is not None and panel.busy:
            panel.stop.set()
            panel.close_after = True
            panel.status.set("正在安全停止标签任务，当前曲目完成后退出…")
            return
        super().close()

    def poll(self):
        try:
            while True:
                kind, generation, value = self.catalog_events.get_nowait()
                if kind in ("catalog", "catalog_error") and generation != self.catalog_generation:
                    continue
                if kind == "catalog":
                    self.render_catalog(value)
                elif kind == "catalog_error":
                    detail, query = value
                    self.current_item = None
                    self.art_generation += 1
                    self.catalog_items.clear()
                    self.catalog_tree.delete(*self.catalog_tree.get_children())
                    self.cover.configure(image="", text="♫")
                    self.album_title.configure(text="目录暂时无法载入")
                    self.album_artist.configure(text="可使用链接直接下载")
                    self.album_detail.configure(text="请检查网络，或稍后重试搜索")
                    self.catalog_note.set("目录查询失败；仍可在「下载与任务」中直接下载链接。" + detail)
                    if query.startswith("https://music.apple.com/"):
                        self.links.delete("1.0", "end")
                        self.links.insert("1.0", query)
                elif kind == "art" and generation == self.art_generation and value:
                    self.art_image = tk.PhotoImage(master=self.root, data=value)
                    self.cover.configure(image=self.art_image, text="")
        except queue.Empty:
            pass
        super().poll()

    def load_recent(self):
        self.library_tree.delete(*self.library_tree.get_children())
        recent = []
        library = Path(self.vars["output"].get()).resolve()
        for path in sorted((ROOT / "logs").glob("*.json"), reverse=True)[:60]:
            try:
                report = json.loads(path.read_text(encoding="utf-8"))
                results = report.get("results", [])
                if any(r.get("output") and Path(r["output"]).resolve().is_relative_to(library) for r in results) or any(
                    d.get("folder") and Path(d["folder"]).resolve().is_relative_to(library) for d in report.get("downloads", [])
                ):
                    recent.append(report)
            except (ValueError, OSError):
                continue
        for report in recent[:15]:
            results = report.get("results", [])
            successful = sum(r["status"] in ("完成", "已验证并跳过") for r in results)
            failed = sum(r["status"] == "失败" for r in results)
            title = Path(results[0]["source"]).parent.name if results else "下载任务"
            self.library_tree.insert("", "end", values=(report["id"][:15], title, f"成功 {successful} / 失败 {failed}"))
        if recent and not self.busy and not self.row_results:
            report = recent[0]
            self.last_report = report
            for result in report.get("results", []):
                row = self.tree.insert("", "end", values=(Path(result["source"]).name, result["preset"].upper(), result["status"], result["detail"]), tags=("failed" if result["status"] == "失败" else "ok",))
                self.row_results[row] = result
            self.phase.set(f"最近任务：{len(report.get('results', []))} 个输出；可在「下载与任务」查看")


def main():
    try:
        import ctypes
        # Let Windows scale pixel layout and point-sized fonts together.
        ctypes.windll.shcore.SetProcessDpiAwareness(0)
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    # Preserve native Retina scaling.
    AppleMusicApp(root)
    from mac_runtime import configure_window
    configure_window(root)
    root.mainloop()


if __name__ == "__main__":
    main()
