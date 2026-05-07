import tkinter as tk
from PIL import Image, ImageTk, ImageDraw, ImageFilter

def create_rounded_rect(width, height, radius, color, border_color=None, border_width=0):
    """Create a rounded rectangle image with antialiasing and optional border."""
    # Scale up for antialiasing
    scale = 2
    w, h, r = width * scale, height * scale, radius * scale
    bw = border_width * scale
    
    image = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    if border_color and bw > 0:
        draw.rounded_rectangle((0, 0, w, h), radius=r, fill=border_color)
        draw.rounded_rectangle((bw, bw, w-bw, h-bw), radius=max(0, r-bw), fill=color)
    else:
        draw.rounded_rectangle((0, 0, w, h), radius=r, fill=color)
    
    image = image.resize((width, height), Image.LANCZOS)
    return ImageTk.PhotoImage(image)

class RoundedFrame(tk.Canvas):
    """A frame with rounded corners, optional border, and sleek look."""
    def __init__(self, parent, width, height, radius=15, bg="#0b0d12", color="#1e2230", border_color=None, border_width=0, **kw):
        super().__init__(parent, width=width, height=height, bg=bg, highlightthickness=0, **kw)
        self.radius = radius
        self.color = color
        self.border_color = border_color
        self.border_width = border_width
        self.rect_image = None
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, event):
        w, h = event.width, event.height
        if w < 1 or h < 1: return
        
        self.delete("bg_rect")
        self.rect_image = create_rounded_rect(w, h, self.radius, self.color, self.border_color, self.border_width)
        self.create_image(0, 0, image=self.rect_image, anchor="nw", tags="bg_rect")
        self.tag_lower("bg_rect")

class AnimatedButton(tk.Canvas):
    """A premium button with hover and optional outlined style."""
    def __init__(
        self,
        parent,
        text="",
        command=None,
        bg="#ff2d47",
        fg="#ffffff",
        hover_bg="#ff4560",
        font=("Segoe UI", 10, "bold"),
        radius=12,
        width=150,
        height=45,
        border_color=None,
        hover_border_color=None,
    ):
        super().__init__(parent, width=width, height=height, bg=parent["bg"] if "bg" in parent.keys() else "#05070a", highlightthickness=0, cursor="hand2")
        self.command = command
        self.text = text
        self.bg = bg
        self.hover_bg = hover_bg
        self.border_color = border_color
        self.hover_border_color = hover_border_color or border_color
        self.fg = fg
        self.font = font
        self.radius = radius
        
        self._normal_img = create_rounded_rect(
            width, height, radius, bg, border_color=border_color, border_width=1 if border_color else 0
        )
        self._hover_img = create_rounded_rect(
            width, height, radius, hover_bg, border_color=self.hover_border_color, border_width=1 if self.hover_border_color else 0
        )
        
        self._bg_id = self.create_image(0, 0, image=self._normal_img, anchor="nw")
        self._txt_id = self.create_text(width/2, height/2, text=text, fill=fg, font=font)
        
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", lambda _: self._on_click())

    def _on_enter(self, e):
        self.itemconfig(self._bg_id, image=self._hover_img)

    def _on_leave(self, e):
        self.itemconfig(self._bg_id, image=self._normal_img)

    def _on_click(self):
        if self.command: self.command()

class ModernEntry(RoundedFrame):
    """A sleek entry field with a rounded container and focus glow."""
    def __init__(self, parent, width, height, radius=15, bg="#05070a", color="#121723", border_color="#1f2937", placeholder="", focus_border="#ff2d47", **kw):
        super().__init__(parent, width, height, radius, bg, color, border_color, border_width=1, **kw)
        self.default_border_color = border_color
        self.focus_border = focus_border
        self.entry = tk.Entry(self, bg=color, fg="#ffffff", insertbackground="#ffffff", relief="flat", font=("Segoe UI", 12), borderwidth=0)
        self.create_window(radius, height/2, window=self.entry, anchor="w", width=width-(radius*2))
        
        if placeholder:
            self.entry.insert(0, placeholder)
            self.entry.config(fg="#4b5563")
            self.entry.bind("<FocusIn>", lambda _: self._clear_placeholder(placeholder))
            self.entry.bind("<FocusOut>", lambda _: self._set_placeholder(placeholder))

    def _clear_placeholder(self, p):
        if self.entry.get() == p:
            self.entry.delete(0, tk.END)
            self.entry.config(fg="#ffffff")
            self.border_color = self.focus_border
            self._on_resize(type('obj', (object,), {'width': self.winfo_width(), 'height': self.winfo_height()}))

    def _set_placeholder(self, p):
        if not self.entry.get():
            self.entry.insert(0, p)
            self.entry.config(fg="#4b5563")
            self.border_color = self.default_border_color
            self._on_resize(type('obj', (object,), {'width': self.winfo_width(), 'height': self.winfo_height()}))

    def get(self):
        return self.entry.get()
    
    def set(self, val):
        self.entry.delete(0, tk.END)
        self.entry.insert(0, val)
        self.entry.config(fg="#ffffff")
