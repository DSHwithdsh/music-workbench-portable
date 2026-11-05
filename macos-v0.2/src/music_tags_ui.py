"""Local tag/lyrics matching workspace; networking and writes run off the UI thread."""
import dataclasses
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from music_core import ROOT
from music_catalog import artwork_png
from music_matching import Matcher, MatchCancelled, lyric_text
from music_tags import SUPPORTED, FIELDS, TagWriter, launch_musictag, proposed_changes, read_track


class TagPanel(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.events = queue.Queue()
        self.busy = False
        self.stop = threading.Event()
        self.rows = {}
        self.close_after = False
        self.folder = tk.StringVar(value=app.vars["output"].get())
        self.overwrite = tk.BooleanVar(value=False)
        self.replace_lyrics = tk.BooleanVar(value=False)
        self.cover = tk.BooleanVar(value=True)
        self.auto_apply = tk.BooleanVar(value=False)
        self.only_confident = tk.BooleanVar(value=True)
        self.query = tk.StringVar()
        self.status = tk.StringVar(value="选择文件或文件夹，自动检索标签和歌词，预览后写入。")
        self.latest_backup = ROOT / "tag-backups"
        self._build()
        self.after(100, self.poll)

    def _build(self):
        self.app.heading(self, "标签与歌词", "自动匹配标签、封面与同步歌词；写入前备份并校验音频不变。")
        row = ttk.Frame(self)
        row.pack(fill="x")
        ttk.Entry(row, textvariable=self.folder).pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.folder_button = ttk.Button(row, text="选择文件夹", command=self.pick_folder)
        self.folder_button.pack(side="left", padx=(0, 8))
        self.files_button = ttk.Button(row, text="选择文件", command=self.pick_files)
        self.files_button.pack(side="left", padx=(0, 8))
        self.scan_button = ttk.Button(row, text="读取文件夹", command=self.scan_folder)
        self.scan_button.pack(side="left")
        actions = ttk.Frame(self)
        actions.pack(fill="x", pady=(10, 7))
        self.match_button = ttk.Button(actions, text="自动匹配所选", style="Accent.TButton", command=self.match_selected)
        self.match_button.pack(side="left", padx=(0, 8))
        self.write_button = ttk.Button(actions, text="写入匹配结果", command=self.write_selected)
        self.write_button.pack(side="left", padx=(0, 8))
        self.candidate_button = ttk.Button(actions, text="查看／选择候选", command=self.choose_candidates)
        self.candidate_button.pack(side="left", padx=(0, 8))
        self.musictag_button = ttk.Button(actions, text="在外部标签应用中打开", command=self.open_musictag)
        self.musictag_button.pack(side="right")
        self.stop_button = ttk.Button(actions, text="停止", command=self.stop.set, state="disabled")
        self.stop_button.pack(side="right", padx=8)
        options = ttk.Frame(self)
        options.pack(fill="x", pady=(0, 7))
        self.option_widgets = []
        for label, variable in (("更新已有标签", self.overwrite), ("替换已有歌词／LRC", self.replace_lyrics),
                                ("补全封面", self.cover), ("仅写入高置信度或确认项", self.only_confident),
                                ("匹配后自动补全", self.auto_apply)):
            widget = ttk.Checkbutton(options, text=label, variable=variable, command=self.preview)
            widget.pack(side="left", padx=(0, 12))
            self.option_widgets.append(widget)
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(frame, columns=("file", "title", "artist", "metadata", "lyrics", "state"), show="headings", selectmode="extended", height=4)
        for key, text, width in (("file", "文件", 205), ("title", "歌名", 170), ("artist", "艺人", 105),
                                 ("metadata", "标签匹配", 100), ("lyrics", "歌词匹配", 105), ("state", "结果", 150)):
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width, minwidth=55)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.tag_configure("ok", foreground="#26734a")
        self.tree.tag_configure("review", foreground="#a65c00")
        self.tree.tag_configure("error", foreground="#b9152e")
        self.tree.bind("<<TreeviewSelect>>", self.preview)
        self.tree.bind("<Double-1>", self.choose_candidates)
        self.details = scrolledtext.ScrolledText(self, height=3, font=("PingFang SC", 9), wrap="word", bg="#f5f5f7", relief="flat", padx=8, pady=7, state="disabled")
        self.details.pack(fill="x", pady=(9, 7))
        row = ttk.Frame(self)
        row.pack(fill="x")
        ttk.Label(row, text="检索词", style="Muted.TLabel").pack(side="left", padx=(0, 7))
        ttk.Entry(row, textvariable=self.query).pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.custom_button = ttk.Button(row, text="按检索词匹配当前项", command=self.match_custom)
        self.custom_button.pack(side="left")
        ttk.Button(row, text="打开标签备份", command=lambda: self.app.open_folder(self.latest_backup)).pack(side="right", padx=(8, 0))
        ttk.Label(self, textvariable=self.status, wraplength=980, style="Muted.TLabel").pack(anchor="w", pady=(8, 0))

    def set_busy(self, value):
        self.busy = value
        self.app.tagging_busy = value
        for button in (self.folder_button, self.files_button, self.scan_button, self.match_button,
                       self.write_button, self.candidate_button, self.musictag_button, self.custom_button, *self.option_widgets):
            button.configure(state="disabled" if value else "normal")
        self.stop_button.configure(state="normal" if value else "disabled")
        self.app.set_controls(not value and not self.app.busy)

    def available(self):
        if self.busy or self.app.busy:
            self.status.set("请等待正在进行的下载、转码或标签任务完成。")
            return False
        return True

    def pick_folder(self):
        folder = filedialog.askdirectory(title="选择待匹配标签和歌词的文件夹")
        if folder:
            self.folder.set(folder)
            self.scan_folder()

    def pick_files(self):
        paths = filedialog.askopenfilenames(title="选择待匹配音频", filetypes=[("音乐文件", "*.m4a *.flac *.mp3 *.mp4")])
        if paths:
            self.load_paths(paths)

    def scan_folder(self):
        folder = Path(self.folder.get().strip())
        if not folder.is_dir():
            messagebox.showerror("标签与歌词", "文件夹不存在", parent=self.app.root)
            return
        self.load_paths(None, folder=folder)

    def load_recent(self):
        report = self.app.last_report
        if not report:
            self.status.set("暂无本次任务结果，请先选择文件。")
            return
        paths = [r["output"] for r in report.get("results", []) if r.get("output") and r["status"] in ("完成", "已验证并跳过")]
        if not paths:
            self.status.set("本次任务没有可匹配的成品。")
            return
        self.load_paths(paths, auto_match=True)

    def load_paths(self, paths, folder=None, auto_match=False):
        if not self.available():
            return
        self.stop.clear()
        self.set_busy(True)
        self.status.set("正在读取音频标签与文件校验信息…")
        def worker():
            loaded, errors = [], []
            try:
                items = paths
                if folder is not None:
                    items = []
                    for current, directories, files in os.walk(folder, followlinks=False):
                        directories[:] = [d for d in directories if not d.startswith(".") and d not in ("backups", "tag-backups", "portable-build", "_vendor") and not (Path(current) / d).is_symlink()]
                        items.extend(Path(current) / f for f in files if Path(f).suffix.lower() in SUPPORTED)
                for path in sorted({Path(p).resolve() for p in items if Path(p).suffix.lower() in SUPPORTED}):
                    if self.stop.is_set():
                        break
                    try:
                        loaded.append(read_track(path))
                    except Exception as exc:
                        errors.append(f"{Path(path).name}: {exc}")
                self.events.put(("loaded", (loaded, errors, auto_match)))
            except Exception as exc:
                self.events.put(("fatal", str(exc)))
        threading.Thread(target=worker, daemon=False).start()

    def selected(self):
        return [row for row in self.tree.selection() if row in self.rows]

    def match_custom(self):
        selected = self.selected()
        if selected and self.query.get().strip():
            self.match_selected(rows=selected[:1], query=self.query.get().strip())

    def match_selected(self, rows=None, query=""):
        if not self.available():
            return
        rows = rows or self.selected()
        if not rows:
            self.status.set("请先选择要匹配的曲目，可 Ctrl / Shift 多选。")
            return
        self.stop.clear()
        self.set_busy(True)
        auto_apply = self.auto_apply.get()
        country = self.app.catalog_country.get()
        replace = self.replace_lyrics.get()
        self.status.set(f"正在匹配 {len(rows)} 个文件；仅发送歌名、艺人、专辑和时长，不上传音频。")
        def worker():
            matcher = Matcher(country, self.stop)
            try:
                for index, row in enumerate(rows, 1):
                    if self.stop.is_set():
                        break
                    local = dict(self.rows[row]["track"])
                    if replace:
                        local["lyrics"] = local["sidecar_lyrics"] = ""
                    match = matcher.match(local, query)
                    self.events.put(("matched", (row, match, index, len(rows))))
                self.events.put(("match_done", auto_apply and not self.stop.is_set()))
            except MatchCancelled:
                self.events.put(("match_done", False))
            except Exception as exc:
                self.events.put(("fatal", str(exc)))
        threading.Thread(target=worker, daemon=False).start()

    def refresh_row(self, row, state=""):
        entry = self.rows[row]
        track, match = entry["track"], entry.get("match") or {}
        meta, lyric = match.get("metadata"), match.get("lyric")
        def score(candidate):
            if not candidate:
                return "无匹配"
            return ("确认 " if candidate.get("accepted") else "") + f"{candidate.get('score', 0):.0%}"
        _, kind = lyric_text(lyric)
        saved = entry.get("state") in ("完成", "无变化")
        tag = "ok" if saved or (meta and meta.get("ready")) or (lyric and lyric.get("ready")) else "review"
        metadata_text = "已保存" if saved else (score(meta) if entry.get("match") else "待检索")
        lyrics_text = kind + (" " + score(lyric) if lyric else "")
        if saved or not entry.get("match"):
            from music_matching import is_synced
            existing = track.get("lyrics") or track.get("sidecar_lyrics")
            lyrics_text = ("同步歌词" if is_synced(existing) else "纯文本歌词") if existing else ("暂无歌词" if saved else "待检索")
        self.tree.item(row, values=(Path(track["path"]).name, track["title"], track["artist"], metadata_text, lyrics_text, state or entry.get("state", "待匹配")), tags=("error" if state.startswith("失败") else tag,))

    def preview(self, _event=None):
        selected = self.selected()
        if not selected:
            return
        entry = self.rows[selected[0]]
        track, match = entry["track"], entry.get("match") or {}
        text = [track["path"], f"时长 {track['duration']:.2f} 秒 · {'已有封面' if track['cover'] else '无封面'}"]
        text.append(f"现有：{track['title']} / {track['artist']} / {track['album']} · 专辑艺人：{track['albumartist'] or '空'} · 流派：{track['genre'] or '空'}")
        fields, lyrics, kind = proposed_changes(track, match, self.overwrite.get(), self.replace_lyrics.get(), self.only_confident.get())
        labels = dict(title="歌名", artist="艺人", album="专辑", albumartist="专辑艺人", date="日期", genre="流派", tracknumber="音轨", discnumber="碟片")
        text.extend(f"{labels[key]}: {track.get(key, '') or '空'} → {value}" for key, value in fields.items())
        meta, lyric = match.get("metadata"), match.get("lyric")
        if meta:
            text.append(f"标签候选：{meta['title']} / {meta['artist']} / {meta['album']} · {meta['score']:.0%} · {meta.get('review_reason', '')}")
        if lyric:
            text.append(f"歌词来源：{lyric['provider']} · {kind} · {len(lyrics.splitlines())} 行 · {'可写入' if lyric.get('ready') or lyric.get('accepted') else '需确认候选'}")
        text.extend(match.get("errors", []))
        if entry.get("detail"):
            text.append(entry["detail"])
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", "\n".join(text))
        self.details.configure(state="disabled")

    def choose_candidates(self, _event=None):
        selected = self.selected()
        if not selected or self.busy:
            return
        row = selected[0]
        match = self.rows[row].get("match")
        if not match:
            self.status.set("请先自动匹配该曲目。")
            return
        window = tk.Toplevel(self)
        window.title("确认标签／歌词候选")
        window.geometry("900x550")
        window.transient(self.app.root)
        window.grab_set()
        for title, key, selected_key in (("标签候选", "metadata_candidates", "metadata"), ("歌词候选", "lyrics_candidates", "lyric")):
            frame = ttk.LabelFrame(window, text=title, padding=10)
            frame.pack(fill="both", expand=True, padx=12, pady=8)
            listing = tk.Listbox(frame, height=6, font=("PingFang SC", 10), exportselection=False)
            listing.pack(fill="both", expand=True)
            values = match.get(key, [])
            for item in values:
                listing.insert("end", f"{item['score']:.0%} | {item['title']} | {item['artist']} | {item.get('album', '')} | {item.get('duration', 0):.1f}s")
            def accept(items=values, box=listing, chosen=selected_key):
                if box.curselection():
                    candidate = dict(items[box.curselection()[0]])
                    candidate["accepted"] = True
                    match[chosen] = candidate
                    self.refresh_row(row, "已确认候选，待写入")
                    self.preview()
            ttk.Button(frame, text="采用所选候选（尚不写文件）", command=accept).pack(anchor="e", pady=(7, 0))

    def write_selected(self):
        if not self.available():
            return
        selected = [row for row in self.selected() if self.rows[row].get("match")]
        if not selected:
            self.status.set("请先自动匹配并选择曲目。")
            return
        settings = self.app.read_settings()
        self.stop.clear()
        self.set_busy(True)
        options = (self.overwrite.get(), self.replace_lyrics.get(), self.only_confident.get())
        cover_enabled = self.cover.get()
        self.status.set("正在备份、写入并校验；进行中的曲目完成后才会停止。")
        def worker():
            writer = TagWriter(settings)
            self.latest_backup = writer.backup_root
            try:
                for index, row in enumerate(selected, 1):
                    if self.stop.is_set():
                        break
                    entry = self.rows[row]
                    track, match = entry["track"], entry["match"]
                    try:
                        fields, text, kind = proposed_changes(track, match, *options)
                        metadata = match.get("metadata")
                        cover = None
                        if cover_enabled and not track["cover"] and metadata and (metadata.get("ready") or metadata.get("accepted")):
                            try:
                                cover = artwork_png(metadata, settings.ffmpeg, size=600)
                            except Exception:
                                pass
                        providers = [{"provider": x.get("provider"), "id": x.get("id"), "score": x.get("score")} for x in (metadata, match.get("lyric")) if x]
                        result = writer.write(track, fields, text, kind, cover, replace_lyrics=options[1], providers=providers)
                        updated = read_track(track["path"])
                        self.events.put(("written", (row, result, updated, index, len(selected))))
                    except Exception as exc:
                        self.events.put(("write_error", (row, str(exc))))
                self.events.put(("write_done", None))
            except Exception as exc:
                self.events.put(("fatal", str(exc)))
        threading.Thread(target=worker, daemon=False).start()

    def open_musictag(self):
        if not self.available():
            return
        selected = self.selected()
        folders = {Path(self.rows[row]["track"]["path"]).parent for row in selected}
        if len(folders) > 1:
            messagebox.showinfo("MusicTag", "请先选择同一个文件夹的曲目。MusicTag 将载入该文件夹。", parent=self.app.root)
            return
        folder = next(iter(folders)) if folders else Path(self.folder.get())
        try:
            launch_musictag(self.app.vars["musictag"].get(), folder)
            self.status.set("已请求打开外部标签应用；编辑并保存后返回重新读取文件夹。")
        except Exception as exc:
            messagebox.showerror("MusicTag", str(exc), parent=self.app.root)

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "loaded":
                    tracks, errors, auto_match = value
                    self.tree.delete(*self.tree.get_children())
                    self.rows.clear()
                    for track in tracks:
                        row = self.tree.insert("", "end")
                        self.rows[row] = {"track": track, "match": None}
                        self.refresh_row(row)
                    self.tree.selection_set(self.tree.get_children())
                    self.set_busy(False)
                    self.status.set(f"已读取 {len(tracks)} 个文件" + (f"，失败 {len(errors)}：{errors[0]}" if errors else "。已选中全部，可开始自动匹配。"))
                    if auto_match and tracks and not self.stop.is_set():
                        self.match_selected()
                elif kind == "matched":
                    row, match, index, total = value
                    self.rows[row]["match"] = match
                    self.refresh_row(row, "预览就绪" if match.get("metadata") or match.get("lyric") else "无匹配／检索失败")
                    self.status.set(f"匹配 {index}/{total}：{Path(self.rows[row]['track']['path']).name}")
                    self.preview()
                elif kind == "match_done":
                    self.set_busy(False)
                    self.status.set("匹配已停止。" if self.stop.is_set() else "匹配完成。可查看候选与变更预览，再写入结果。")
                    if value:
                        self.write_selected()
                elif kind == "written":
                    row, result, updated, index, total = value
                    self.rows[row].update(track=updated, match=None, state=result["status"], detail="标签备份：" + result["backup"])
                    self.refresh_row(row, result["status"] + " · 音频不变")
                    self.status.set(f"写入 {index}/{total} · {Path(updated['path']).name} · {result['status']}")
                    self.preview()
                elif kind == "write_error":
                    row, error = value
                    self.rows[row]["detail"] = error
                    self.refresh_row(row, "失败：" + error)
                    self.preview()
                elif kind == "write_done":
                    self.set_busy(False)
                    self.status.set("写入已结束；逐曲结果见列表，原文件备份位于 tag-backups。")
                elif kind == "fatal":
                    self.set_busy(False)
                    self.status.set("任务未完成：" + value)
        except queue.Empty:
            pass
        if self.close_after and not self.busy:
            self.app.root.destroy()
            return
        self.after(100, self.poll)
