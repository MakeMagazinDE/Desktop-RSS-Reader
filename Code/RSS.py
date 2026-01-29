# ICON deployed-code
# NAME MAKE-RSS
# DESC Die aktuellsten MAKE-beiträge.
from presto import Presto
from touch import Button
import time
import gc
import qrcode

try:
    import urequests as requests
except ImportError:
    import requests

FEED_URL = "https://makemagazinde.github.io/Desktop-RSS-Reader/feed.xml"
REFRESH_INTERVAL = 30 * 60
MAX_ITEMS = 20

presto = Presto(full_res=True)
display = presto.display
touch = presto.touch

WIDTH, HEIGHT = display.get_bounds()

BLACK = display.create_pen(0, 0, 0)
WHITE = display.create_pen(255, 255, 255)
GREY = display.create_pen(150, 150, 150)
ACCENT = display.create_pen(0, 180, 255)

btn_next = Button(0, 0, WIDTH // 3, HEIGHT)
btn_prev = Button(2 * WIDTH // 3, 0, WIDTH // 3, HEIGHT - 80)
# Button unten rechts für QR-Code-Toggle
qr_btn = Button(WIDTH - 80, HEIGHT - 80, 80, 80)


articles = []
current_index = 0
last_refresh = 0
last_timer_draw = 0
qr_visible = False


def clear_screen(color_pen=None):
    if color_pen is None:
        color_pen = BLACK
    display.set_pen(color_pen)
    display.clear()


def show_message(lines, color_pen=None):
    clear_screen()
    if color_pen is None:
        color_pen = WHITE
    display.set_pen(color_pen)
    display.set_font("bitmap8")
    y = 40
    for line in lines:
        display.text(line, 20, y, wordwrap=WIDTH - 40, scale=1)
        y += 20
    presto.update()


def strip_tags(text):
    out = []
    inside = False
    for ch in text:
        if ch == "<":
            inside = True
            continue
        if ch == ">":
            inside = False
            continue
        if not inside:
            out.append(ch)
    return "".join(out)


def connect_wifi():
    show_message(["Verbinde mit WLAN...", "", "Bitte warten"])
    try:
        presto.connect()  # nutzt secrets.py
        show_message(["WLAN verbunden!"])
        time.sleep(1)
    except Exception as e:
        show_message(["WLAN-Fehler:", str(e)[:25]], color_pen=ACCENT)
        time.sleep(3)


def get_tag_text(block, tag):
    open_pos = block.find("<" + tag)
    if open_pos == -1:
        return ""

    start = block.find(">", open_pos)
    if start == -1:
        return ""
    start += 1

    close_tag = "</" + tag + ">"
    end = block.find(close_tag, start)
    if end == -1:
        return ""

    text = block[start:end].strip()
    text = text.replace("<![CDATA[", "").replace("]]>", "")
    return text

def draw_mini_qr_button():
    x0 = WIDTH - 70
    y0 = HEIGHT - 70

    display.set_pen(GREY)
    display.rectangle(x0, y0, 60, 60)

    display.set_pen(BLACK)

    display.rectangle(x0 + 6, y0 + 6, 12, 12)
    display.rectangle(x0 + 10, y0 + 10, 4, 4)

    display.rectangle(x0 + 42, y0 + 6, 12, 12)
    display.rectangle(x0 + 46, y0 + 10, 4, 4)

    display.rectangle(x0 + 6, y0 + 42, 12, 12)
    display.rectangle(x0 + 10, y0 + 46, 4, 4)

    display.rectangle(x0 + 30, y0 + 30, 6, 6)
    display.rectangle(x0 + 34, y0 + 18, 6, 6)
    display.rectangle(x0 + 22, y0 + 40, 6, 6)


def fetch_rss():
    global articles, current_index, last_refresh

    show_message(["Hole Feed...", "", FEED_URL[:40]], color_pen=ACCENT)

    try:
        r = requests.get(FEED_URL, timeout=10)
        xml = r.text
        r.close()
    except Exception as e:
        show_message(["HTTP-Fehler:", str(e)[:25]], color_pen=ACCENT)
        time.sleep(3)
        return

    parsed = []

    if "<item" in xml:
        items = xml.split("<item")
        blocks = items[1:MAX_ITEMS + 1]
        is_atom = False
    elif "<entry" in xml:
        items = xml.split("<entry")
        blocks = items[1:MAX_ITEMS + 1]
        is_atom = True
    else:
        blocks = []
        is_atom = False

    for raw in blocks:
        block = raw

        title = get_tag_text(block, "title") or ""
        if is_atom:
            desc = get_tag_text(block, "summary") or get_tag_text(block, "content") or ""
            link = ""
            link_pos = raw.find("<link")
            if link_pos != -1:
                link_end = raw.find(">", link_pos)
                if link_end == -1:
                    link_end = link_pos + 200
                tag_chunk = raw[link_pos:link_end]
                href_pos = tag_chunk.find('href="')
                if href_pos != -1:
                    href_pos += len('href="')
                    href_end = tag_chunk.find('"', href_pos)
                    if href_end != -1:
                        link = tag_chunk[href_pos:href_end]
        else:
            desc = get_tag_text(block, "description") or ""
            link = get_tag_text(block, "link") or ""

        title = strip_tags(title)
        desc = strip_tags(desc)

        if len(desc) > 400:
            desc = desc[:400] + " …"

        if title:
            parsed.append(
                {
                    "title": title,
                    "description": desc,
                    "link": link,
                }
            )

    if parsed:
        articles = parsed
        current_index = 0
        last_refresh = time.time()
        gc.collect()
        render_current_article()
    else:
        show_message(["Keine Einträge gefunden"], color_pen=ACCENT)
        time.sleep(3)


def render_current_article():
    clear_screen()
    display.set_font("bitmap8")

    if not articles:
        display.set_pen(WHITE)
        display.text(
            "Keine Artikel geladen",
            20,
            HEIGHT // 2 - 10,
            wordwrap=WIDTH - 40,
            scale=2,
        )
        presto.update()
        return

    article = articles[current_index]
    title = article["title"]
    desc = article["description"]
    link = article.get("link", "")

    display.set_pen(ACCENT)
    display.text(
        "RSS Reader",
        10,
        10,
        wordwrap=WIDTH - 20,
        scale=2,
    )

    now = time.time()
    if last_refresh == 0:
        timer_text = "Nächste Aktualisierung: unbekannt"
    else:
        remaining = REFRESH_INTERVAL - (now - last_refresh)
        if remaining <= 0:
            timer_text = "Aktualisiere gleich..."
        else:
            mins = int(remaining // 60)
            secs = int(remaining % 60)
            mm = f"{mins:02d}"
            ss = f"{secs:02d}"
            timer_text = f"Nächstes Update in {mm}:{ss}"

    display.set_pen(GREY)
    display.text(
        timer_text,
        10,
        50,
        wordwrap=WIDTH - 20,
        scale=1.5,
    )

    display.set_pen(GREY)
    info = f"{current_index + 1}/{len(articles)}"
    display.text(info, WIDTH - 90, 50, wordwrap=80, scale=1.5)

    display.set_pen(WHITE)
    y = 90
    display.text(
        title,
        10,
        y,
        wordwrap=WIDTH - 20,
        scale=2,
    )

    y += 70 + (len(title) // 20) * 22

    display.set_pen(GREY)
    display.text(
        desc,
        10,
        y,
        wordwrap=WIDTH - 20,
        scale=2,
    )

    display.set_pen(ACCENT)
    display.text(
        "< links = neuer    |    neuer = älter >",
        10,
        HEIGHT - 30,
        wordwrap=WIDTH - 20,
        scale=2,
    )

    if qr_visible:
        draw_qr(link)

    draw_mini_qr_button()

    presto.update()

def measure_qr_code(max_size, code):
    w, h = code.get_size()          # Anzahl Module (z.B. 29x29)
    module_size = int(max_size / w) # Pixel pro Modul
    pixel_size = module_size * w    # tatsächliche Pixelgröße (quadratisch)
    return pixel_size, module_size


def draw_qr(link):
    if not link:
        return

    try:
        code = qrcode.QRCode()
        code.set_text(link)

        max_qr_size = HEIGHT - 150
        qr_pixel_size, module_size = measure_qr_code(max_qr_size, code)

        w, h = code.get_size()

        x0 = (WIDTH - qr_pixel_size) // 2
        y0 = HEIGHT - qr_pixel_size - 60

        if y0 < 130:
            y0 = 130

        display.set_pen(BLACK)
        display.rectangle(x0 - 4, y0 - 4, qr_pixel_size + 8, qr_pixel_size + 8)

        for yy in range(h):
            for xx in range(w):
                if code.get_module(xx, yy):
                    display.set_pen(WHITE)
                else:
                    display.set_pen(BLACK)
                display.rectangle(
                    x0 + xx * module_size,
                    y0 + yy * module_size,
                    module_size,
                    module_size,
                )

    except Exception as e:
        print("QR-Fehler:", e)


def handle_touch():
    global current_index

    touch.poll()

    next_pressed = btn_next.is_pressed()
    prev_pressed = btn_prev.is_pressed()

    if next_pressed:
        if current_index > 0:
            current_index -= 1
            render_current_article()
            time.sleep_ms(500)

    if prev_pressed:
        if current_index < len(articles) - 1:
            current_index += 1
            render_current_article()
            time.sleep_ms(500)

    if qr_btn.is_pressed():
        global qr_visible
        qr_visible = not qr_visible
        render_current_article()


def start():
    global last_refresh, last_timer_draw

    presto.set_backlight(1.0)
    show_message(["RSS Reader startet..."])

    connect_wifi()
    fetch_rss()

    last_timer_draw = time.time()

    while True:
        now = time.time()

        if now - last_refresh > REFRESH_INTERVAL:
            fetch_rss()

        handle_touch()

        if now - last_timer_draw >= 1:
            render_current_article()
            last_timer_draw = now

        time.sleep(0.05)



start()



