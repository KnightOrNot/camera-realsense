"""Optional Tk image preview."""

from __future__ import annotations

import time

from PIL import Image


class Preview:
    """Optional Tk preview; CLI capture does not need a display."""

    def __init__(self):
        try:
            import tkinter as tk
            from PIL import ImageTk
            self.root = tk.Tk()
        except Exception as exc:
            raise RuntimeError(f"无法创建预览窗口：{exc}。可去掉 --preview 进行无窗口测试。") from exc
        self.ImageTk = ImageTk
        self.root.title("RealSense USB2 测试 — Q / Esc 退出")
        self.label = tk.Label(self.root)
        self.label.pack()
        self.closed = False
        self.photo = None
        self.updated_at = 0.0
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Escape>", lambda _: self.close())
        self.root.bind("q", lambda _: self.close())

    def close(self):
        self.closed = True

    def pump(self) -> bool:
        if not self.closed:
            self.root.update_idletasks()
            self.root.update()
        return not self.closed

    def show(self, images):
        if time.monotonic() - self.updated_at < 1 / 15:
            return
        pictures = [Image.fromarray(image).convert("RGB") for image in images]
        canvas = Image.new("RGB", (sum(p.width for p in pictures), max(p.height for p in pictures)))
        x = 0
        for picture in pictures:
            canvas.paste(picture, (x, 0))
            x += picture.width
        canvas.thumbnail((1280, 720))
        self.photo = self.ImageTk.PhotoImage(canvas)
        self.label.configure(image=self.photo)
        self.updated_at = time.monotonic()

    def destroy(self):
        self.root.destroy()
