"""Chinese desktop front end for the local music pipeline."""
from __future__ import annotations

import os
import queue
import subprocess
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from music_core import ROOT, Pipeline, Settings, parse_links, scan_folder, service_status


class MusicApp:
    def __init__(self, root):
        self.root = root
        self.root.title("AMDL × fre:ac · 音乐工作台")
        self.root.geometry("1080x700")
        self.root.minsize(920, 730)
        self.root.configure(bg="#f3f6f8")
        self.events = queue.Queue()
        self.pipeline = None
        self.busy = False
        self.total = 0
        self.completed = 0
        self.closing = False
        self.last_report = None
        self.service_process = None
        try:
            self.settings = Settings.load()
        except Exception as exc:
            self.settings = Settings()
            self.events.put(("log", f"设置读取失败，已使用默认路径：{exc}"))
        self.mode = tk.StringVar(value="both")
        self.source_mode = tk.StringVar(value="folder")
        self.source_folder = tk.StringVar(value=str(ROOT / "Music/ALAC"))
        self.file_selection = []
        self.vars = {name: tk.StringVar(value=str(getattr(self.settings, name)))
                     for name in ("amdl_root", "freac", "output", "workers", "storefront", "musictag")}
        self.phase = tk.StringVar(value="就绪 · 粘贴链接下载，或选择已有音频转码")
        self.service = tk.StringVar(value="正在检查解密服务…")
        self._style()
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self.poll)
        self.root.after(200, self.refresh_service)

    def _style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", font=("PingFang SC", 10), background="#f3f6f8", foreground="#263849")
        style.configure("TNotebook", borderwidth=0)
        style.configure("TNotebook.Tab", padding=(18, 9))
        style.configure("TButton", padding=(12, 7))
        style.configure("Accent.TButton", background="#007f75", foreground="white", font=("PingFang SC", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#00695f"), ("disabled", "#b9c8c9")])
        style.configure("Title.TLabel", font=("PingFang SC", 22, "bold"))
        style.configure("Muted.TLabel", foreground="#5c7080", font=("PingFang SC", 9))
        style.configure("TLabelframe.Label", font=("PingFang SC", 10, "bold"))
        style.configure("Treeview", background="white", fieldbackground="white", rowheight=27)
        style.configure("Treeview.Heading", font=("PingFang SC", 9, "bold"), padding=5)
        style.configure("TProgressbar", background="#007f75", troughcolor="#dfe8ec")

    def _build(self):
        outer = ttk.Frame(self.root, padding=(22, 16))
        outer.pack(fill="both", expand=True)
        title = ttk.Frame(outer)
        title.pack(fill="x")
        ttk.Label(title, text="音乐工作台", style="Title.TLabel").pack(side="left")
        ttk.Label(title, text="AMDL 下载  →  fre:ac 转码  →  音频校验", style="Muted.TLabel").pack(side="left", padx=18, pady=(10, 0))
        service_row = ttk.Frame(outer)
        service_row.pack(fill="x", pady=(10, 12))
        ttk.Label(service_row, textvariable=self.service).pack(side="left")
        self.service_button = ttk.Button(service_row, text="打开解密服务窗口", command=self.open_service)
        self.service_button.pack(side="right")
        ttk.Button(service_row, text="刷新状态", command=self.refresh_service).pack(side="right", padx=7)

        self.tabs = ttk.Notebook(outer)
        self.tabs.pack(fill="x")
        download_tab = ttk.Frame(self.tabs, padding=15)
        convert_tab = ttk.Frame(self.tabs, padding=15)
        settings_tab = ttk.Frame(self.tabs, padding=15)
        self.tabs.add(download_tab, text="下载并转换")
        self.tabs.add(convert_tab, text="本地音频转码")
        self.tabs.add(settings_tab, text="路径与设置")

        ttk.Label(download_tab, text="Apple Music 专辑／歌单／单曲链接（每行一个）").pack(anchor="w")
        self.links = scrolledtext.ScrolledText(download_tab, height=4, wrap="word", font=("Segoe UI", 10), relief="flat", padx=8, pady=7)
        self.links.pack(fill="x", pady=7)
        row = ttk.Frame(download_tab)
        row.pack(fill="x")
        ttk.Label(row, text="下载 ALAC 原始无损；单曲链接会自动识别。", style="Muted.TLabel").pack(side="left")
        self.download_button = ttk.Button(row, text="开始下载并处理", style="Accent.TButton", command=self.start_download)
        self.download_button.pack(side="right")

        source_row = ttk.Frame(convert_tab)
        source_row.pack(fill="x")
        ttk.Radiobutton(source_row, text="整个文件夹（含子目录）", variable=self.source_mode, value="folder").pack(side="left")
        ttk.Radiobutton(source_row, text="指定音频文件", variable=self.source_mode, value="files").pack(side="left", padx=16)
        self.source_entry = ttk.Entry(convert_tab, textvariable=self.source_folder)
        self.source_entry.pack(fill="x", pady=9)
        row = ttk.Frame(convert_tab)
        row.pack(fill="x")
        ttk.Button(row, text="选择文件夹", command=self.choose_source_folder).pack(side="left")
        ttk.Button(row, text="选择音频文件…", command=self.choose_files).pack(side="left", padx=8)
        self.selection_label = ttk.Label(row, text="尚未选择单独文件", style="Muted.TLabel")
        self.selection_label.pack(side="left")
        self.convert_button = ttk.Button(row, text="开始转码", style="Accent.TButton", command=self.start_convert)
        self.convert_button.pack(side="right")
        ttk.Label(convert_tab, text="保留原目录层级、文件名和内嵌标签／封面；同名 LRC 随成品复制。有损输入会跳过。", style="Muted.TLabel").pack(anchor="w", pady=(10, 0))

        for index, (label, key) in enumerate((("AMDL 安装目录", "amdl_root"), ("freaccmd.exe", "freac"), ("音乐库输出目录", "output"))):
            ttk.Label(settings_tab, text=label).grid(row=index, column=0, sticky="w", padx=(0, 10), pady=4)
            ttk.Entry(settings_tab, textvariable=self.vars[key]).grid(row=index, column=1, sticky="ew", pady=4)
            ttk.Button(settings_tab, text="浏览…", command=lambda k=key: self.browse_setting(k)).grid(row=index, column=2, padx=(8, 0), pady=4)
        settings_tab.columnconfigure(1, weight=1)
        options = ttk.Frame(settings_tab)
        options.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(9, 0))
        ttk.Label(options, text="并行曲目数").pack(side="left")
        ttk.Spinbox(options, from_=1, to=10, width=4, textvariable=self.vars["workers"]).pack(side="left", padx=(8, 18))
        ttk.Label(options, text="AMDL 商店地区").pack(side="left")
        ttk.Entry(options, width=5, textvariable=self.vars["storefront"]).pack(side="left", padx=8)
        self.save_button = ttk.Button(options, text="保存并检查路径", command=self.save_settings)
        self.save_button.pack(side="right")
        ttk.Label(settings_tab, text="地区应与账号对应。原 AMDL 的 config.yaml 继续生效；输出目录由本工具指定。", style="Muted.TLabel").grid(row=4, column=0, columnspan=3, sticky="w", pady=(8, 0))

        preset = ttk.LabelFrame(outer, text="输出方案", padding=(12, 8))
        preset.pack(fill="x", pady=(12, 7))
        self.preset_buttons = []
        for text, value in (("FLAC + AAC-LC 256k", "both"), ("仅 FLAC（等级 6）", "flac"), ("仅 AAC-LC 256k", "aac"), ("仅下载 ALAC", "none")):
            button = ttk.Radiobutton(preset, text=text, value=value, variable=self.mode)
            button.pack(side="left", padx=(0, 15))
            self.preset_buttons.append(button)
        output_row = ttk.Frame(outer)
        output_row.pack(fill="x", pady=(0, 10))
        ttk.Label(output_row, text="音乐库：", style="Muted.TLabel").pack(side="left")
        ttk.Label(output_row, textvariable=self.vars["output"], style="Muted.TLabel").pack(side="left", fill="x", expand=True)
        ttk.Button(output_row, text="打开音乐库", command=self.open_output).pack(side="right")

        self.tree = ttk.Treeview(outer, columns=("file", "preset", "status", "detail"), show="headings", height=5)
        for column, label, width in (("file", "曲目", 290), ("preset", "格式", 80), ("status", "状态", 125), ("detail", "校验／说明", 420)):
            self.tree.heading(column, text=label)
            self.tree.column(column, width=width, minwidth=60)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", self.show_result)
        self.tree.tag_configure("failed", foreground="#b53b3b")
        self.tree.tag_configure("ok", foreground="#007f75")
        self.row_results = {}

        progress_row = ttk.Frame(outer)
        progress_row.pack(fill="x", pady=(10, 3))
        self.phase_label = ttk.Label(progress_row, textvariable=self.phase, wraplength=790)
        self.phase_label.pack(side="left", fill="x", expand=True)
        self.stop_button = ttk.Button(progress_row, text="完成当前曲目后停止", command=self.request_stop, state="disabled")
        self.stop_button.pack(side="right")
        self.progress = ttk.Progressbar(outer, mode="determinate")
        self.progress.pack(fill="x", pady=(4, 8))
        self.log_view = scrolledtext.ScrolledText(outer, height=6, wrap="word", font=("PingFang SC", 9), background="#eaf0f4", relief="flat", padx=8, pady=7, state="disabled")
        self.log_view.pack(fill="x")
        footer = ttk.Frame(outer)
        footer.pack(fill="x", pady=(7, 0))
        ttk.Label(footer, text="原文件保留 · 成品校验后提交 · 已有成品校验后跳过 · 双击结果查看详情", style="Muted.TLabel").pack(side="left")
        ttk.Button(footer, text="日志与任务报告", command=lambda: self.open_folder(ROOT / "logs")).pack(side="right")

    def read_settings(self):
        data = {key: variable.get().strip() for key, variable in self.vars.items()}
        data["workers"] = int(data["workers"])
        return Settings(**data)

    def save_settings(self):
        try:
            settings = self.read_settings()
            settings.check(download=True)
            settings.save()
            self.settings = settings
            self.append_log("设置已保存，AMDL、fre:ac 和 FFmpeg 路径均可用")
            self.phase.set("设置已保存，路径检查通过")
        except Exception as exc:
            messagebox.showerror("设置检查", str(exc), parent=self.root)

    def browse_setting(self, key):
        if key in ("freac", "musictag"):
            value = filedialog.askopenfilename(title="选择 freaccmd 或外部标签应用", filetypes=[("所有文件", "*")])
        else:
            value = filedialog.askdirectory(title="选择工具目录" if key == "amdl_root" else "选择音乐库目录")
        if value:
            self.vars[key].set(value)


    def choose_source_folder(self):
        value = filedialog.askdirectory(title="选择已有无损音频目录")
        if value:
            self.source_folder.set(value)
            self.source_mode.set("folder")

    def choose_files(self):
        values = filedialog.askopenfilenames(title="选择音频文件", filetypes=[("音频文件", "*.m4a *.flac *.wav *.aif *.aiff *.alac *.mp3 *.aac *.ogg *.opus"), ("所有文件", "*.*")])
        if values:
            self.file_selection = [Path(value) for value in values]
            self.source_mode.set("files")
            self.selection_label.configure(text=f"已选 {len(values)} 个文件")

    def refresh_service(self):
        def check():
            self.events.put(("service", service_status()))
        threading.Thread(target=check, daemon=True).start()

    def open_service(self):
        try:
            ports = service_status()
            if all(ports.values()):
                self.append_log("端口已就绪，继续使用现有服务")
                self.refresh_service()
                return
            if any(ports.values()):
                raise ValueError("只有一个服务端口就绪，请先检查已有服务")
            from mac_runtime import launch_service
            launch_service()
            self.append_log("已请求在终端打开独立 Docker 服务；请在其中登录，完成后刷新服务状态")
            self.root.after(3000, self.refresh_service)
        except Exception as exc:
            messagebox.showerror("启动解密服务", str(exc), parent=self.root)

    def get_presets(self):
        return {"both": ("flac", "aac"), "flac": ("flac",), "aac": ("aac",), "none": ()}[self.mode.get()]

    def start_download(self):
        try:
            links = parse_links(self.links.get("1.0", "end"))
            settings = self.read_settings()
            settings.check(download=True)
            presets = self.get_presets()
            self.start(settings, lambda pipe: pipe.download(links, presets), downloading=True)
        except Exception as exc:
            messagebox.showerror("下载任务", str(exc), parent=self.root)

    def start_convert(self):
        try:
            settings = self.read_settings()
            settings.check()
            presets = self.get_presets()
            if not presets:
                raise ValueError("本地转码请先选择 FLAC 或 AAC 输出方案")
            if self.source_mode.get() == "folder":
                source_root = Path(self.source_folder.get().strip()).resolve()
                # Scanning can be expensive; perform it in the worker below.
                def work(pipe):
                    files = scan_folder(source_root, settings.output)
                    pipe.log(f"扫描完成：{len(files)} 个音频文件")
                    pipe.convert(files, source_root, presets)
            else:
                files = list(self.file_selection)
                if not files:
                    raise ValueError("请先选择音频文件")
                source_root = Path(os.path.commonpath([str(path.parent) for path in files]))
                def work(pipe):
                    pipe.convert(files, source_root, presets)
            self.start(settings, work)
        except Exception as exc:
            messagebox.showerror("本地转码", str(exc), parent=self.root)

    def start(self, settings, work, downloading=False):
        if self.busy:
            return
        settings.save()
        self.settings = settings
        self.pipeline = Pipeline(settings, lambda kind, value: self.events.put((kind, value)))
        self.busy = True
        self.completed = self.total = 0
        self.tree.delete(*self.tree.get_children())
        self.row_results.clear()
        self.progress.configure(mode="indeterminate", value=0)
        self.progress.start(15)
        self.phase.set("正在下载；停止将在当前链接完成后生效" if downloading else "正在扫描并校验源音频…")
        self.set_controls(False)
        self.stop_button.configure(state="normal", text="当前链接完成后停止" if downloading else "完成当前曲目后停止")
        self.append_log(f"任务 {self.pipeline.id} 开始。输出目录：{settings.output}")

        def worker():
            fatal = ""
            try:
                work(self.pipeline)
            except Exception as exc:
                fatal = str(exc)
                self.pipeline.log("任务错误：" + fatal)
            finally:
                try:
                    report = self.pipeline.finish(fatal)
                    self.events.put(("done", report))
                except Exception as exc:
                    self.events.put(("done", {"fatal": f"无法写入报告：{exc}", "results": [], "downloads": []}))
        threading.Thread(target=worker, daemon=False).start()

    def set_controls(self, enabled):
        state = "normal" if enabled else "disabled"
        for widget in (self.download_button, self.convert_button, self.save_button, *self.preset_buttons):
            widget.configure(state=state)
        # Settings widgets remain readable; edits apply only to the next task.

    def request_stop(self):
        if self.pipeline:
            self.pipeline.stop.set()
            self.phase.set("正在安全停止：等待进行中的下载链接／曲目完成，后续任务不再开始")
            self.stop_button.configure(state="disabled")

    def append_log(self, text):
        self.log_view.configure(state="normal")
        self.log_view.insert("end", text + "\n")
        if int(self.log_view.index("end-1c").split(".")[0]) > 1500:
            self.log_view.delete("1.0", "300.0")
        self.log_view.see("end")
        self.log_view.configure(state="disabled")

    def poll(self):
        try:
            for _ in range(250):
                kind, value = self.events.get_nowait()
                if kind == "log":
                    self.append_log(value)
                elif kind == "service":
                    text = " · ".join(f"{port} {'已就绪' if ready else '未启动'}" for port, ready in value.items())
                    self.service.set("解密服务：" + text)
                elif kind == "phase":
                    self.phase.set(value)
                    self.stop_button.configure(text="完成当前曲目后停止" if "转码" in value else "当前链接完成后停止")
                elif kind == "download_progress":
                    name = value.get("name", "")
                    number = value.get("track_num", value.get("tracknum", ""))
                    count = value.get("total_tracks", value.get("totaltracks", ""))
                    quality = value.get("streamgroup", value.get("codec", "ALAC"))
                    if name and not self.pipeline.stop.is_set():
                        self.phase.set(f"下载 {number}/{count} · {name} · {quality}")
                elif kind == "total":
                    self.total = value
                    self.progress.stop()
                    self.progress.configure(mode="determinate", maximum=max(1, value), value=self.completed)
                elif kind == "result":
                    self.completed += 1
                    tag = "failed" if value["status"] == "失败" else "ok"
                    item = self.tree.insert("", "end", values=(Path(value["source"]).name, value["preset"].upper(), value["status"], value["detail"]), tags=(tag,))
                    self.row_results[item] = value
                    self.tree.see(item)
                    self.progress.configure(value=self.completed)
                    self.phase.set(f"已处理 {self.completed}/{self.total} 个输出")
                elif kind == "done":
                    self.busy = False
                    self.last_report = value
                    self.progress.stop()
                    self.progress.configure(mode="determinate", maximum=max(1, self.total), value=self.completed)
                    self.set_controls(True)
                    self.stop_button.configure(state="disabled")
                    successes = sum(r["status"] == "完成" for r in value["results"])
                    skipped = sum(r["status"] == "已验证并跳过" for r in value["results"])
                    failures = sum(r["status"] == "失败" for r in value["results"])
                    canceled = sum(r["status"] == "已取消" for r in value["results"])
                    warnings = sum(d["status"] != "完成" for d in value["downloads"])
                    prefix = "已停止" if value.get("stopped") else "任务结束"
                    summary = f"{prefix} · 完成 {successes} · 已验证跳过 {skipped} · 失败 {failures} · 取消 {canceled} · 下载需检查 {warnings}"
                    self.phase.set(summary)
                    self.append_log(summary)
                    self.append_log(f"详细报告：{self.pipeline.report_path}")
                    if value.get("fatal"):
                        messagebox.showerror("任务未完成", value["fatal"], parent=self.root)
                    if self.closing:
                        self.root.destroy()
                        return
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def show_result(self, _event=None):
        selected = self.tree.selection()
        if selected:
            result = self.row_results[selected[0]]
            messagebox.showinfo("曲目结果", f"源文件：{result['source']}\n\n输出：{result['output']}\n\n{result['status']}\n{result['detail']}", parent=self.root)

    def open_folder(self, path):
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
            from mac_runtime import open_folder
            open_folder(path)
        except Exception as exc:
            messagebox.showerror("打开目录", str(exc), parent=self.root)

    def open_output(self):
        value = self.vars["output"].get().strip()
        if value:
            self.open_folder(Path(value))

    def close(self):
        if self.busy:
            if messagebox.askyesno("安全退出", "任务还在进行。完成进行中的曲目或下载链接后停止并退出？", parent=self.root):
                self.closing = True
                self.request_stop()
        else:
            self.root.destroy()


def main():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    MusicApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
