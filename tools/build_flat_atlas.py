import argparse
import json
from pathlib import Path

from PIL import Image


def load_atlas(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def extract_sprite(sheet: Image.Image, frame: dict) -> Image.Image:
    fr = frame["frame"]
    sss = frame.get("spriteSourceSize") or {"x": 0, "y": 0, "w": fr["w"], "h": fr["h"]}
    src_size = frame.get("sourceSize") or {"w": fr["w"], "h": fr["h"]}

    rotated = bool(frame.get("rotated"))
    if rotated:
        # Rotated frames in the atlas are stored swapped (w/h). Crop the swapped area, then rotate back.
        crop_box = (fr["x"], fr["y"], fr["x"] + fr["h"], fr["y"] + fr["w"])
    else:
        crop_box = (fr["x"], fr["y"], fr["x"] + fr["w"], fr["y"] + fr["h"])

    crop = sheet.crop(crop_box)
    if rotated:
        # TexturePacker-style rotation: restore to original orientation.
        crop = crop.transpose(Image.ROTATE_90)

    full = Image.new("RGBA", (src_size["w"], src_size["h"]), (0, 0, 0, 0))
    full.paste(crop, (sss["x"], sss["y"]))
    return full


def pack_sprites(items, max_width: int, padding: int):
    items = sorted(items, key=lambda it: it["h"], reverse=True)
    x = padding
    y = padding
    shelf_h = 0
    placed = []
    for it in items:
        w = it["w"] + padding * 2
        h = it["h"] + padding * 2
        if x + w > max_width and x > padding:
            x = padding
            y += shelf_h
            shelf_h = 0
        placed.append({**it, "x": x + padding, "y": y + padding})
        x += w
        shelf_h = max(shelf_h, h)
    atlas_w = max_width
    atlas_h = y + shelf_h
    return placed, atlas_w, atlas_h


def update_html(html_path: Path, atlas_json_text: str) -> None:
    html = html_path.read_text(encoding="utf-8", errors="replace")

    sheets_block = (
        "<!-- INLINE_SHEETS_START -->\n"
        "<!-- External sheet: assets/flat-sprites.webp -->\n"
        "<!-- INLINE_SHEETS_END -->\n"
    )
    if "<!-- INLINE_SHEETS_START -->" in html and "<!-- INLINE_SHEETS_END -->" in html:
        before, rest = html.split("<!-- INLINE_SHEETS_START -->", 1)
        _, after = rest.split("<!-- INLINE_SHEETS_END -->", 1)
        html = before + sheets_block + after

    atlas_block = (
        "<!-- INLINE_ATLASES_START -->\n"
        "<script id=\"atlasFlat\" type=\"application/json\">\n"
        f"{atlas_json_text}\n"
        "</script>\n"
        "<!-- INLINE_ATLASES_END -->\n"
    )
    if "<!-- INLINE_ATLASES_START -->" in html and "<!-- INLINE_ATLASES_END -->" in html:
        before, rest = html.split("<!-- INLINE_ATLASES_START -->", 1)
        _, after = rest.split("<!-- INLINE_ATLASES_END -->", 1)
        html = before + atlas_block + after

    html = html.replace(
        "const ATLAS_0 = getInlineJson(\"atlas0\");\nconst ATLAS_1 = getInlineJson(\"atlas1\");\n",
        "const ATLAS_0 = getInlineJson(\"atlasFlat\");\nconst ATLAS_1 = { frames: {} };\n",
    )
    html = html.replace(
        "const SHEET_0_SRC = getInlineDataUrl(\"sheet0\");\nconst SHEET_1_SRC = getInlineDataUrl(\"sheet1\");\nconst SHEET_0_FALLBACK = ASSETS_URL + \"/sprites-0.webp\";\nconst SHEET_1_FALLBACK = ASSETS_URL + \"/sprites-1.webp\";\n\n",
        "const SHEET_0_SRC = ASSETS_URL + \"/flat-sprites.webp\";\nconst SHEET_1_SRC = ASSETS_URL + \"/flat-sprites.webp\";\nconst SHEET_0_FALLBACK = null;\nconst SHEET_1_FALLBACK = null;\n\n",
    )

    html_path.write_text(html, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets-dir", required=True)
    parser.add_argument("--out-image", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--max-width", type=int, default=4096)
    parser.add_argument("--padding", type=int, default=2)
    parser.add_argument("--update-html", default=None)
    args = parser.parse_args()

    assets_dir = Path(args.assets_dir)
    sprites0 = assets_dir / "sprites-0.webp"
    sprites1 = assets_dir / "sprites-1.webp"
    atlas0 = assets_dir / "sprites-0.json"
    atlas1 = assets_dir / "sprites-1.json"

    sheet0 = Image.open(sprites0).convert("RGBA")
    sheet1 = Image.open(sprites1).convert("RGBA")

    data0 = load_atlas(atlas0)
    data1 = load_atlas(atlas1)

    frames = []
    for key, frame in (data0.get("frames") or {}).items():
        frames.append({"key": key, "frame": frame, "sheet": 0})
    for key, frame in (data1.get("frames") or {}).items():
        frames.append({"key": key, "frame": frame, "sheet": 1})

    extracted = []
    max_w = 0
    for item in frames:
        frame = item["frame"]
        sheet = sheet0 if item["sheet"] == 0 else sheet1
        sprite = extract_sprite(sheet, frame)
        w, h = sprite.size
        max_w = max(max_w, w)
        extracted.append(
            {
                "key": item["key"],
                "img": sprite,
                "w": w,
                "h": h,
                "anchor": frame.get("anchor", {"x": 0.5, "y": 0.5}),
            }
        )

    max_width = args.max_width
    if max_w + args.padding * 2 > max_width:
        max_width = max(max_w + args.padding * 2, 8192)

    placed, atlas_w, atlas_h = pack_sprites(extracted, max_width, args.padding)
    atlas = Image.new("RGBA", (atlas_w, atlas_h), (0, 0, 0, 0))

    out_frames = {}
    for it in placed:
        atlas.paste(it["img"], (it["x"], it["y"]))
        out_frames[it["key"]] = {
            "frame": {"x": it["x"], "y": it["y"], "w": it["w"], "h": it["h"]},
            "rotated": False,
            "trimmed": False,
            "spriteSourceSize": {"x": 0, "y": 0, "w": it["w"], "h": it["h"]},
            "sourceSize": {"w": it["w"], "h": it["h"]},
            "anchor": it["anchor"],
        }

    out_json = {
        "frames": out_frames,
        "meta": {
            "app": "flat-atlas",
            "version": "1.0",
            "image": Path(args.out_image).name,
            "format": "RGBA8888",
            "size": {"w": atlas_w, "h": atlas_h},
            "scale": "1",
        },
    }

    out_image = Path(args.out_image)
    out_image.parent.mkdir(parents=True, exist_ok=True)
    atlas.save(out_image, format="WEBP", lossless=True, quality=100, method=6)

    out_json_path = Path(args.out_json)
    out_json_path.parent.mkdir(parents=True, exist_ok=True)
    out_json_path.write_text(json.dumps(out_json, separators=(",", ":")), encoding="utf-8")

    if args.update_html:
        update_html(Path(args.update_html), out_json_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
