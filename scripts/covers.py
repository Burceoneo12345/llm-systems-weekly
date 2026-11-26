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
                "Art-direct a wordless illustrated engineering journal. Read the Chinese lead, then write ONE English "
                "sentence of 18–32 words describing a tangible tabletop scene a photographer could stage in daylight. "
                "Give it a recognizable physical object and one visible action that explains this specific mechanism. "
                "For precision comparisons, picture the same shape printed by coarse and fine blocks. For cross-device "
                "dispatch, picture parcels travelling between sorting trays. For synchronized routing, picture "
                "parallel railway switches joined by a common lever. Invent other physical analogies for other leads. "
                "No screens, circuitry, glowing nodes, light beams, data streams, people, writing or technical acronyms. "
                "Return the scene directly."
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
        "OpenVINO/stable-diffusion-xl-base-1.0-int8-ov", revision="d54e5b43fcb6b4b358f3a134269115d3fcb3eb25",
        cache_dir=str(Path.home() / ".cache/weekly-illustration"), max_workers=3,
        allow_patterns=["model_index.json", "scheduler/*", "tokenizer*/*", "text_encoder*/*",
                        "unet/*", "vae_decoder/*", "vae_encoder/*"],
    )
    pipe = openvino_genai.Text2ImagePipeline(model_dir, "CPU")
    for cover in covers:
        path = Path(cover["file"])
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        seed = int.from_bytes(hashlib.sha256(path.name.encode()).digest()[:4], "big")
        palette = ("vermilion and charcoal", "forest green and amber", "ultramarine and copper", "terracotta and teal")[seed % 4]
        prompt = (cover["scene"] + f" A bright editorial still life in {palette}. Bold hand-printed linocut, "
                  "warm ivory paper background, intricate carved lines, generous light, clear object silhouettes.")
        for attempt in range(2):
            result = pipe.generate(prompt, negative_prompt="dark background, neon, abstract network, screens, text, letters, people, blur",
                                   width=896, height=704, num_inference_steps=20, guidance_scale=6.5, rng_seed=seed + attempt)
            image = Image.fromarray(result.data[0])
            light = image.convert("L")
            if ImageStat.Stat(light).stddev[0] >= 24 and sum(light.histogram()[150:]) > 0.06 * light.width * light.height:
                break
        else:
            raise ValueError(f"Insufficient contrast or highlights for {path}")
        temporary = path.with_suffix(".tmp")
        image.save(temporary, "WEBP", quality=88, method=6)
        temporary.replace(path)
        print(f"已生成 {path}", flush=True)
else:
    raise SystemExit("Expected brief or render")
