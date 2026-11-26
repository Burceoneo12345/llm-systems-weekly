"""Turn the lead of each pending issue into an original editorial illustration."""
import hashlib
import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen


stage, manifest = sys.argv[1], Path(sys.argv[2])
covers = json.loads(manifest.read_text())

if stage == "brief":
    for cover in covers:
        messages = [
            {"role": "system", "content": (
                "Art-direct a wordless cover for a computer systems journal. The user gives the lead in Chinese. "
                "Reply with ONE 18–32 word English scene description. Translate the specific mechanism into concrete "
                "visible objects doing something. If it compares alternatives, show their contrast. If it transfers or "
                "routes data, show what moves and where. Pick a different visual subject for different mechanisms. "
                "Avoid generic chips, labels, lettering, performance graphs and unsupported numerical claims. "
                "Describe the scene directly, without a preamble or quotation marks."
            )},
            {"role": "user", "content": json.dumps({"headline": cover["title"], "summary": cover["summary"]}, ensure_ascii=False)}
        ]
        payload = {"model": "weekly-editor", "messages": messages, "max_tokens": 110, "temperature": 0.35,
                   "chat_template_kwargs": {"enable_thinking": False}}
        req = Request("http://127.0.0.1:8089/v1/chat/completions", data=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=180) as response:
            scene = json.load(response)["choices"][0]["message"]["content"].strip()
        if not 6 <= len(scene.split()) <= 65 or not any("a" <= c <= "z" for c in scene.lower()):
            raise ValueError(f"Invalid illustration brief for {cover['title']}: {scene}")
        cover["scene"] = scene
        print(f"{cover['title']} → {scene}", flush=True)
    manifest.write_text(json.dumps(covers, ensure_ascii=False))
elif stage == "render":
    import openvino_genai
    from huggingface_hub import snapshot_download
    from PIL import Image, ImageStat

    model_dir = snapshot_download(
        "OpenVINO/LCM_Dreamshaper_v7-int8-ov", revision="340a03e5488f36f7f222e6efa29819850ad7e4be",
        cache_dir=str(Path.home() / ".cache/weekly-illustration"), max_workers=3,
        allow_patterns=["model_index.json", "scheduler/*", "tokenizer/*", "text_encoder/*",
                        "unet/*", "vae_decoder/*", "vae_encoder/*"],
    )
    pipe = openvino_genai.Text2ImagePipeline(model_dir, "CPU")
    for cover in covers:
        path = Path(cover["file"])
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        seed = int.from_bytes(hashlib.sha256(path.name.encode()).digest()[:4], "big")
        prompt = (cover["scene"] + " Editorial linocut illustration, bold geometric forms, vermilion red, "
                  "charcoal black and warm ivory ink, crisp silhouettes, textured paper, wordless print.")
        result = pipe.generate(prompt, width=640, height=512, num_inference_steps=6, guidance_scale=7.5, rng_seed=seed)
        image = Image.fromarray(result.data[0])
        if image.size != (640, 512) or max(ImageStat.Stat(image).stddev) < 5:
            raise ValueError(f"Cover generation produced an empty image for {path}")
        temporary = path.with_suffix(".tmp")
        image.save(temporary, "WEBP", quality=88, method=6)
        temporary.replace(path)
        print(f"已生成 {path}", flush=True)
else:
    raise SystemExit("Expected brief or render")
