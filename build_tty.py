#!/usr/bin/env python3
"""
build_tty.py — generate the `tty` character pack: a minimalist living-terminal
for the M5Stick Hardware Buddy. All seven states, procedurally rendered, 96px
wide, 2-colour (accent on black), pixel-crisp (small render + nearest upscale).

  python3 build_tty.py [terra|amber]

Writes characters/tty/{manifest.json, *.gif} and a /tmp/tty_sheet.gif preview.
"""
import json
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/liberation/LiberationMono-Bold.ttf"
W0, H0, SCALE = 32, 33, 3
BG = (0, 0, 0)
PALETTES = {"terra": (217, 119, 87), "amber": (255, 176, 0)}
PAL = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in PALETTES else "terra"
ACCENT = PALETTES[PAL]

font = ImageFont.truetype(FONT, 8)
ADV = font.getlength("A")
CAP = font.getbbox("A")[3] - font.getbbox("A")[1]
X0 = 2
Y1 = 13            # single-line baseline
YA, YB = 7, 18     # two-line baselines
OUT = Path(__file__).resolve().parent / "characters" / "tty"

HEART = ["011011", "111111", "111111", "011110", "001100", "000100"]


# --- rendering primitives ------------------------------------------------- #
def colorize(mask, bright):
    mask = mask.point(lambda p: 255 if p > 96 else 0)
    col = tuple(int(c * bright) for c in ACCENT)
    rgb = Image.composite(Image.new("RGB", (W0, H0), col),
                          Image.new("RGB", (W0, H0), BG), mask)
    return rgb.resize((W0 * SCALE, H0 * SCALE), Image.NEAREST)


def frame(fn, bright=1.0):
    m = Image.new("L", (W0, H0), 0)
    fn(ImageDraw.Draw(m))
    return colorize(m, bright)


def txt(d, x, y, s):
    for i, ch in enumerate(s):
        d.text((x + i * ADV, y), ch, font=font, fill=255)


def caret(d, x, y):
    d.rectangle([x, y + 1, x + ADV * 0.85, y + CAP], fill=255)


def heart(d, cx, cy, cell=2):
    for r, row in enumerate(HEART):
        for c, ch in enumerate(row):
            if ch == "1":
                d.rectangle([cx + c * cell, cy + r * cell,
                             cx + c * cell + cell - 1, cy + r * cell + cell - 1], fill=255)


# --- state animations (list of (img, duration_ms)) ------------------------ #
def st_sleep():
    f = lambda b: frame(lambda d: txt(d, X0, Y1, "$ _"), b)
    return [(f(0.30), 1100), (f(0.17), 1100)]


def st_idle0():
    on = frame(lambda d: (txt(d, X0, Y1, "$ "), caret(d, X0 + 2 * ADV, Y1)))
    off = frame(lambda d: txt(d, X0, Y1, "$ "))
    return [(on, 480), (off, 480), (on, 480), (off, 480)]


def st_idle1():
    def f(s, cur):
        return frame(lambda d: (txt(d, X0, Y1, s),
                                caret(d, X0 + len(s) * ADV, Y1) if cur else None))
    return [(f("$ ", 1), 300), (f("$ l", 1), 250), (f("$ ls", 1), 300),
            (f("$ ls", 1), 650), (f("$ ls", 0), 360), (f("$ ls", 1), 360),
            (f("$ ", 1), 520)]


def st_idle2():
    on = frame(lambda d: (txt(d, X0, Y1, "$ "), caret(d, X0 + 2 * ADV, Y1)))
    off = frame(lambda d: txt(d, X0, Y1, "$ "))
    return [(on, 950), (off, 650)]


def st_busy():
    spin, dd = "|/-\\", ["", ".", "..", "..."]
    out = []
    for i in range(16):
        s, dt = spin[i % 4], dd[(i // 2) % 4]
        out.append((frame(lambda d, s=s, dt=dt: txt(d, X0, Y1, f"$ {s}{dt}")), 130))
    return out


def st_attention():
    def f(on):
        return frame(lambda d: (txt(d, X0, YA, "allow?"), txt(d, X0, YB, "[y/n]"),
                                caret(d, X0 + 5 * ADV, YB) if on else None))
    out = []
    for _ in range(5):
        out += [(f(1), 240), (f(0), 240)]
    return out


def st_celebrate():
    out = []
    for n in range(5):
        bar = "[" + "#" * n + " " * (4 - n) + "]"
        out.append((frame(lambda d, bar=bar: (txt(d, X0, YA, "lvl up"),
                                              txt(d, X0, YB, bar))), 150))
    full = "[####]"
    bursts = [[(5, 1), (26, 3), (15, 0)], [(2, 4), (29, 1), (20, 6)], [(9, 2), (24, 5), (13, 0)]]
    for sp in bursts:
        def fn(d, sp=sp):
            txt(d, X0, YA, "lvl up")
            txt(d, X0, YB, full)
            for (x, y) in sp:
                d.text((x, y), "*", font=font, fill=255)
        out.append((frame(fn), 160))
    out.append((frame(lambda d: (txt(d, X0, YA, "lvl up"), txt(d, X0, YB, full))), 500))
    return out


def st_dizzy():
    rest = frame(lambda d: (txt(d, X0, Y1, "$ "), caret(d, X0 + 2 * ADV, Y1)))
    out = [(rest, 250)]
    for i, s in enumerate(["$ #%&", "$ @?!", "$ &*~", "$ %#@", "$ !&#"]):
        jy = Y1 + (-2 if i % 2 else 2)
        out.append((frame(lambda d, s=s, jy=jy: txt(d, X0, jy, s)), 120))
    out.append((rest, 300))
    return out


def st_heart():
    cx = W0 // 2 - 6
    return [(frame(lambda d: heart(d, cx, 9, 2), b), 150)
            for b in (0.5, 0.7, 0.9, 1.0, 0.9, 0.7)]


STATES = {
    "sleep": st_sleep(), "idle_0": st_idle0(), "idle_1": st_idle1(), "idle_2": st_idle2(),
    "busy": st_busy(), "attention": st_attention(), "celebrate": st_celebrate(),
    "dizzy": st_dizzy(), "heart": st_heart(),
}


def save(name, frames):
    imgs = [f[0].convert("P", palette=Image.ADAPTIVE, colors=16) for f in frames]
    durs = [f[1] for f in frames]
    imgs[0].save(OUT / name, save_all=True, append_images=imgs[1:],
                 duration=durs, loop=0, disposal=2, optimize=True)
    return (OUT / name).stat().st_size


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    total = 0
    for name, frames in STATES.items():
        total += save(f"{name}.gif", frames)
    manifest = {
        "name": "tty",
        "colors": {"body": "#%02X%02X%02X" % ACCENT, "bg": "#000000",
                   "text": "#FFFFFF", "textDim": "#808080", "ink": "#000000"},
        "states": {
            "sleep": "sleep.gif",
            "idle": ["idle_0.gif", "idle_1.gif", "idle_2.gif"],
            "busy": "busy.gif", "attention": "attention.gif",
            "celebrate": "celebrate.gif", "dizzy": "dizzy.gif", "heart": "heart.gif",
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"palette={PAL}  wrote {len(STATES)} gifs -> {OUT}")
    for f in sorted(OUT.glob("*.gif")):
        print(f"  {f.name:14s} {f.stat().st_size:>6,}b")
    print(f"  total {total:,}b  (cap 1,800,000)")

    # ---- preview contact sheet (animated grid) ----
    def at(frames, t):
        tot = sum(d for _, d in frames)
        t %= tot
        acc = 0
        for img, d in frames:
            acc += d
            if t < acc:
                return img
        return frames[-1][0]

    lab = ImageFont.truetype("/usr/share/fonts/liberation/LiberationMono-Regular.ttf", 12)
    cells = [("sleep", STATES["sleep"]), ("idle", STATES["idle_1"]), ("busy", STATES["busy"]),
             ("attention", STATES["attention"]), ("celebrate", STATES["celebrate"]),
             ("dizzy", STATES["dizzy"]), ("heart", STATES["heart"])]
    cw, ch = W0 * SCALE, H0 * SCALE
    cols, pad, head = 4, 8, 18
    rows = (len(cells) + cols - 1) // cols
    GW = cols * (cw + pad) + pad
    GH = rows * (ch + head + pad) + pad
    sheet = []
    for k in range(30):
        t = k * 120
        cv = Image.new("RGB", (GW, GH), (16, 16, 18))
        d = ImageDraw.Draw(cv)
        for idx, (nm, fr) in enumerate(cells):
            cx = pad + (idx % cols) * (cw + pad)
            cy = pad + (idx // cols) * (ch + head + pad)
            d.text((cx + 2, cy), nm, font=lab, fill=(140, 140, 150))
            cv.paste(at(fr, t), (cx, cy + head))
            d.rectangle([cx - 1, cy + head - 1, cx + cw, cy + head + ch], outline=(40, 40, 44))
        sheet.append(cv)
    sheet[0].save("/tmp/tty_sheet.gif", save_all=True, append_images=sheet[1:],
                  duration=120, loop=0)
    print("preview -> /tmp/tty_sheet.gif")


if __name__ == "__main__":
    main()
