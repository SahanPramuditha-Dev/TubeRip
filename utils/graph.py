import tkinter as tk
from collections import deque

class SpeedGraph(tk.Canvas):
    """A real-time line graph for download speeds."""
    def __init__(self, parent, width=150, height=40, max_points=30, color="#00a2ff", bg="#0f131a", **kw):
        super().__init__(parent, width=width, height=height, bg=bg, highlightthickness=0, **kw)
        self.max_points = max_points
        self.color = color
        self.points = deque([0] * max_points, maxlen=max_points)
        self.max_val = 1024 * 1024  # Start with 1MB scale
        self.bind("<Configure>", lambda _: self._draw())

    def add_point(self, val: float):
        """Add speed in bps."""
        self.points.append(val)
        self.max_val = max(max(self.points), 1024 * 1024)
        self._draw()

    def _draw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 10 or h < 10: return

        # Draw grid
        self.create_line(0, h//2, w, h//2, fill="#1e293b", dash=(2,2))

        # Map points to coordinates
        coords = []
        dx = w / (self.max_points - 1)
        for i, val in enumerate(self.points):
            x = i * dx
            y = h - (val / self.max_val * (h - 8)) - 4
            coords.extend([x, y])

        if len(coords) >= 4:
            # Subtle glow effect (double line)
            self.create_line(*coords, fill=self.color, width=3, smooth=True)
            self.create_line(*coords, fill="#ffffff", width=1, smooth=True)
            
            # Area fill
            fill_coords = [0, h, *coords, w, h]
            self.create_polygon(*fill_coords, fill=self.color, outline="", stipple="gray25")
