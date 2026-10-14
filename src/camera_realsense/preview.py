"""Optional Tk image preview."""

from __future__ import annotations

from contextlib import contextmanager

import numpy as np
from PIL import Image

from .processing import depth_image


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
        self.root.title("RealSense 预览 — Q / Esc 退出")
        self.label = tk.Label(self.root)
        self.label.pack()
        self.closed = False
        self.photo = None
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
        if not images:
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

    def destroy(self):
        self.root.destroy()


@contextmanager
def preview_session(enabled: bool):
    """The --preview switch controls both window creation and cleanup here."""
    preview = Preview() if enabled else None
    try:
        yield preview
    finally:
        if preview:
            preview.destroy()


def show_preview(preview: Preview | None, frames: dict, max_depth: float = 3) -> None:
    """Show depth pseudocolor, RGB and infrared, shared by all video commands."""
    if preview is None:
        return
    images = []
    for name, frame in frames.items():
        raw = np.asanyarray(frame.get_data())
        images.append(depth_image(raw, frame.get_units(), max_depth) if name == "depth" else raw)
    preview.show(images)
