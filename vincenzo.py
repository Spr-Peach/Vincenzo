#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
用法：
    python civitai_details.py "https://civitai.com/models/1994924/z-imagechromaqwen-anime"

功能：
    - 请求 Civitai 模型页面 HTML
    - 从 <script id="__NEXT_DATA__"> 中解析 JSON
    - 在 trpcState 里找到对应的 model / modelVersion
    - 输出所需字段：
        Type, Published, Base Model, Usage Tips, Trigger Words
    - 某项缺失则输出空字符串
"""

import json
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

import requests
import os
import shutil
from io import BytesIO


from bs4 import BeautifulSoup
try:
    import gradio as gr
except ImportError:
    gr = None

try:
    from PIL import Image
except ImportError:
    Image = None



# ================== 代理设置（从 config.json 读取） ==================
# 若使用代理，请在config.json中设置端口号；若缺失config.json 或将enable_proxy设置为false，则不走代理。

def load_proxies_from_config() -> Optional[Dict[str, str]]:
    """从 config.json 中读取代理配置，返回给 requests 使用的 proxies 字典。

    返回值示例：{"http": "http://127.0.0.1:49254", "https": "http://127.0.0.1:49254"}
    如果未启用代理或配置无效，则返回 None。
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "config.json")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except FileNotFoundError:
        # 没有配置文件，默认不走代理
        return None
    except Exception as e:
        print(f"[warn] 读取 config.json 失败：{e}，将不使用代理")
        return None

    enable_proxy = bool(cfg.get("enable_proxy"))
    if not enable_proxy:
        return None

    host = str(cfg.get("proxy_host", "127.0.0.1")).strip() or "127.0.0.1"
    port_raw = cfg.get("proxy_port", 0)
    try:
        port = int(port_raw)
    except Exception:
        print(f"[warn] config.json 中的 proxy_port 无效：{port_raw}，将不使用代理")
        return None

    if port <= 0:
        print("[warn] config.json 中的 proxy_port 必须为正整数，将不使用代理")
        return None

    proxy_url = f"http://{host}:{port}"
    return {"http": proxy_url, "https": proxy_url}

PROXIES: Optional[Dict[str, str]] = load_proxies_from_config()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

TARGET_FIELDS = ["Type", "Published", "Base Model", "Usage Tips", "Trigger Words", "Hash", "File Name"]


def extract_ids_from_url(url: str) -> Tuple[Optional[int], Optional[int]]:
    """
    从 URL 中抽出 modelId 和可选的 modelVersionId。
    例如:
      https://civitai.com/models/2185778/z-image...
      https://civitai.com/models/2185778?modelVersionId=123456
    """
    m = re.search(r"/models/(\d+)", url)
    model_id = int(m.group(1)) if m else None

    vm = re.search(r"[?&]modelVersionId=(\d+)", url)
    version_id = int(vm.group(1)) if vm else None

    return model_id, version_id


def fetch_html(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=30, proxies=PROXIES)
    resp.raise_for_status()
    return resp.text


def extract_next_data(html: str) -> Any:
    """
    从 HTML 中找出 __NEXT_DATA__ 的 JSON。
    """
    m = re.search(
        r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return None

    raw = m.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # 简单兜底：有时会 HTML 实体编码
        raw = raw.replace("&quot;", '"')
        return json.loads(raw)


def extract_preview_image_url(html: str) -> Optional[str]:
    """从页面 HTML 中粗略提取第一张预览图的 URL。

    规则：
      1. 优先找 class 里包含 EdgeImage_image__ 且 src 来自 image.civitai.com 的 <img>
      2. 如果找不到，再兜底：页面上第一张 src 含 image.civitai.com 的图片
    """
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return None

    # 方案 A：优先 EdgeImage_image__
    for img in soup.find_all("img"):
        src = img.get("src") or ""
        classes = " ".join(img.get("class") or [])
        if "image.civitai.com" in src and "EdgeImage_image__" in classes:
            return src

    # 方案 B：兜底，只要来自 image.civitai.com 的第一张图片
    for img in soup.find_all("img"):
        src = img.get("src") or ""
        if "image.civitai.com" in src:
            return src

    return None


def find_model_from_trpc(next_data: Any, model_id: Optional[int]) -> Optional[Dict[str, Any]]:
    """
    在 trpcState.json.queries 里找到 queryKey = ["model","getById"] 的那条，
    并返回其中的 state.data。
    """
    try:
        queries: List[Dict[str, Any]] = (
            next_data["props"]["pageProps"]["trpcState"]["json"]["queries"]
        )
    except Exception:
        return None

    candidate = None

    for q in queries:
        key = q.get("queryKey")
        if not isinstance(key, list) or not key:
            continue
        # key 形如: [ ["model","getById"], {"input": {...}} ]
        first = key[0]
        if (
            isinstance(first, list)
            and len(first) >= 2
            and first[0] == "model"
            and first[1] == "getById"
        ):
            data = q.get("state", {}).get("data")
            if not isinstance(data, dict):
                continue
            if model_id is None or data.get("id") == model_id:
                return data
            candidate = data  # 作为兜底

    return candidate


def choose_model_version(
    model_data: Dict[str, Any], version_id: Optional[int]
) -> Optional[Dict[str, Any]]:
    versions = model_data.get("modelVersions")
    if not isinstance(versions, list) or not versions:
        return None

    if version_id is not None:
        for v in versions:
            try:
                if int(v.get("id")) == version_id:
                    return v
            except Exception:
                continue

    # 没指定版本时：优先按 publishedAt 降序找最近的一个
    def _published_ts(v: Dict[str, Any]) -> str:
        return str(v.get("publishedAt") or "")

    versions_sorted = sorted(versions, key=_published_ts, reverse=True)
    return versions_sorted[0]


def build_usage_tips(version: Dict[str, Any]) -> str:
    """
    页面 Details 里的 Usage Tips 一般显示：
      CLIP SKIP: 1   STRENGTH: 1
    这边用 clipSkip + settings 里的 strength/min/max 拼一个字符串。
    """
    clip_skip = version.get("clipSkip")
    settings = version.get("settings") or {}
    strength = settings.get("strength")
    min_s = settings.get("minStrength")
    max_s = settings.get("maxStrength")

    parts: List[str] = []

    if clip_skip is not None:
        parts.append(f"CLIP SKIP: {clip_skip}")

    if strength is not None:
        # 如果有 min/max，就顺便带上
        if min_s is not None or max_s is not None:
            extra = []
            if min_s is not None:
                extra.append(f"min {min_s}")
            if max_s is not None:
                extra.append(f"max {max_s}")
            parts.append(f"STRENGTH: {strength} ({', '.join(extra)})")
        else:
            parts.append(f"STRENGTH: {strength}")

    return " | ".join(parts)


def fetch_real_filename(file_url: str) -> Optional[str]:
    """
    对文件直链发送 HEAD 请求，从 Content-Disposition 中取真实下载文件名。
    如果失败就返回 None。
    """
    try:
        resp = requests.head(file_url, headers=HEADERS, timeout=30, proxies=PROXIES, allow_redirects=True)
        cd = resp.headers.get("Content-Disposition") or resp.headers.get("content-disposition")
        if not cd:
            return None

        # 常见格式类似：attachment; filename="AmeAni.safetensors"
        m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd, re.IGNORECASE)
        if not m:
            return None

        filename = m.group(1).strip()
        # 有些情况下可能是 URL 编码
        try:
            from urllib.parse import unquote
            filename = unquote(filename)
        except Exception:
            pass

        return filename
    except Exception:
        return None


def fetch_preview_image_url_from_api(
    model_id: Optional[int],
    version_id: Optional[int],
) -> Optional[str]:
    """通过 Civitai 的公开 API 获取某个 modelVersion 的第一张预览图 URL。
    优先匹配 version_id，对不上就退回第一个版本。
    """
    if model_id is None:
        return None

    api_url = f"https://civitai.com/api/v1/models/{model_id}"
    try:
        resp = requests.get(api_url, headers=HEADERS, timeout=30, proxies=PROXIES)
        resp.raise_for_status()
    except Exception as e:
        print(f"[warn] 调用 Civitai API 失败：{e}")
        return None

    try:
        data = resp.json()
    except Exception:
        return None

    versions = data.get("modelVersions") or []
    if not versions:
        return None

    chosen = None
    if version_id is not None:
        for v in versions:
            try:
                if int(v.get("id")) == int(version_id):
                    chosen = v
                    break
            except Exception:
                continue

    if chosen is None:
        chosen = versions[0]

    images = chosen.get("images") or []
    if not images:
        return None

    first = images[0]
    url = (
        first.get("url")
        or first.get("urlSmall")
        or first.get("urlThumbnail")
    )
    if not url:
        return None

    return str(url).strip()



def save_preview_image(
    preview_url: Optional[str],
    model_file_name: str,
    proxies: Optional[Dict[str, str]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> None:
    """根据模型文件名保存预览图到 ./output/xxx.png。

    - 如果给出了 preview_url，则先尝试直接下载
    - 若下载失败或 preview_url 为空，则复制脚本目录下的 default.png
    - 所有图片统一保存到脚本根目录下的 output 文件夹中
    """
    # 1. 计算输出目录与目标文件路径
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    base, _ = os.path.splitext(model_file_name or "")
    if not base:
        base = "preview"
    target_path = os.path.join(output_dir, base + ".png")

    # 2. 若有 preview_url，优先尝试下载
    if preview_url:
        try:
            resp = requests.get(
                preview_url,
                headers=headers or {},
                proxies=proxies,
                timeout=30,
            )
            resp.raise_for_status()
            content = resp.content

            # 尽量通过 Pillow 统一转成标准 RGB PNG，避免缩略图异常
            if Image is not None:
                try:
                    img = Image.open(BytesIO(content))
                    img.load()  # 强制解码

                    # 如果带有透明通道或其他奇怪的 mode，就铺一层白底转成 RGB
                    if img.mode not in ("RGB", "L"):
                        background = Image.new("RGB", img.size, (255, 255, 255))
                        if "A" in img.getbands():
                            alpha = img.split()[-1]
                            background.paste(img, mask=alpha)
                        else:
                            background.paste(img)
                        img = background
                    else:
                        img = img.convert("RGB")

                    img.save(target_path, format="PNG")
                    return
                except Exception:
                    # Pillow 失败就退回到直接写原始内容
                    pass

            # 没装 Pillow 或转换失败时的兜底：直接写原始内容
            with open(target_path, "wb") as f:
                f.write(content)
            return
        except Exception as e:
            # 下载失败则退回使用 default.png
            print(f"[warn] 下载预览图失败：{e}，使用 default.png 代替")

    # 3. 使用默认图 default.png
    default_path = os.path.join(script_dir, "default.png")
    if os.path.exists(default_path):
        try:
            shutil.copyfile(default_path, target_path)
        except Exception as e:
            print(f"[warn] 复制 default.png 失败：{e}")
    else:
        print(f"[warn] default.png 不存在，无法为 {target_path} 生成预览图")


# 新增：保存详情到 txt 文件
def save_details_txt(
    details: Dict[str, str],
    url: str,
) -> None:
    """把抓取到的字段写入 output/file_name.txt 里面，并附上一行 URL。"""
    # 1. 计算输出目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    # 2. 计算基础文件名：优先用 File Name（去掉扩展名）
    file_name = details.get("File Name", "") or ""
    base, _ = os.path.splitext(file_name)
    if not base:
        # 如果实在拿不到模型文件名，就兜底一个占位名字
        base = "model"

    txt_path = os.path.join(output_dir, base + ".txt")

    # 3. 按行写入所有字段 + URL
    lines: List[str] = []
    for key in TARGET_FIELDS:
        value = details.get(key, "")
        lines.append(f"{key}: {value}")
    lines.append(f"URL: {url}")

    text = "\n".join(lines) + "\n"

    try:
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception as e:
        print(f"[warn] 写入详情 TXT 失败：{e}")


def extract_fields(
    model_data: Optional[Dict[str, Any]],
    version_data: Optional[Dict[str, Any]],
) -> Dict[str, str]:
    result: Dict[str, str] = {k: "" for k in TARGET_FIELDS}

    if not model_data:
        return result

    # Type：模型大类
    result["Type"] = str(model_data.get("type") or "").strip()

    if not version_data:
        return result

    # Published：版本发布时间（比 model 的 publishedAt 更贴近侧栏显示）
    published = (
        version_data.get("publishedAt")
        or model_data.get("publishedAt")
        or ""
    )
    result["Published"] = str(published).strip()

    # Base Model
    base_model = (
        version_data.get("baseModel")
        or version_data.get("baseModelType")
        or ""
    )
    result["Base Model"] = str(base_model).strip()

    # Trigger Words
    trained = version_data.get("trainedWords") or []
    if isinstance(trained, (list, tuple)):
        words = [str(w).strip() for w in trained if str(w).strip()]
        result["Trigger Words"] = ", ".join(words)
    else:
        result["Trigger Words"] = str(trained).strip()

    # Usage Tips：用 clipSkip + settings 拼
    result["Usage Tips"] = build_usage_tips(version_data)

    # ======================  新增：Hash  ======================
    hash_value = ""
    file_name = ""
    files = version_data.get("files") or []
    for f in files:
        # 只取模型文件（通常 type 为 'Model'）
        if f.get("type") == "Model" or f.get("type") == "model":
            # 先尝试通过 HEAD 请求拿真实下载文件名
            file_url = f.get("url")
            if file_url:
                real_name = fetch_real_filename(file_url)
                if real_name:
                    file_name = real_name
                else:
                    # 兜底：用 JSON 里的 name 字段
                    file_name = str(f.get("name") or "").strip()

            raw_hashes = f.get("hashes") or []
            auto_v2 = ""
            hash_type = "AUTOV2"

            # hashes 可能是 list，也可能是 dict，我们都兼容一下
            if isinstance(raw_hashes, dict):
                auto_v2 = str(
                    raw_hashes.get("AutoV2")
                    or raw_hashes.get("AUTOV2")
                    or ""
                ).strip()
            elif isinstance(raw_hashes, (list, tuple)):
                # 优先找 AutoV2，没有就退而求其次
                preferred_order = ["AUTOV2", "AutoV2", "SHA256", "SHA1", "CRC32"]
                chosen_type = ""
                chosen_hash = ""

                for t in preferred_order:
                    for h in raw_hashes:
                        if not isinstance(h, dict):
                            continue
                        ht = str(h.get("type") or "").upper()
                        if ht == t.upper() and h.get("hash"):
                            chosen_type = ht
                            chosen_hash = str(h["hash"]).strip()
                            break
                    if chosen_hash:
                        break

                if chosen_hash:
                    hash_type = chosen_type
                    auto_v2 = chosen_hash

            if auto_v2:
                hash_value = f"{hash_type} | {auto_v2}"
            break

    result["Hash"] = hash_value
    result["File Name"] = file_name
    # ======================  Hash 结束 =======================

    return result


def extract_details_from_url(url: str) -> Tuple[Dict[str, str], Optional[str]]:
    """抓取模型详情字段，同时返回预览图 URL（如果能找到的话）。"""
    model_id, version_id = extract_ids_from_url(url)
    html = fetch_html(url)

    next_data = extract_next_data(html)
    if next_data is None:
        # 没有 JSON 也先试着从 HTML 里刮一张图
        preview_url = extract_preview_image_url(html)
        empty = {k: "" for k in TARGET_FIELDS}
        # 再用 API 兜底一次
        if not preview_url:
            preview_url = fetch_preview_image_url_from_api(model_id, version_id)
        return empty, preview_url

    model_data = find_model_from_trpc(next_data, model_id)
    version_data = choose_model_version(model_data, version_id) if model_data else None

    details = extract_fields(model_data, version_data)

    # 1️⃣ 优先通过 API 拿预览图（与模型版本严格对应）
    preview_url = fetch_preview_image_url_from_api(model_id, version_id)

    # 2️⃣ 如果 API 没给，再从 HTML 里刮图兜底
    if not preview_url:
        preview_url = extract_preview_image_url(html)

    return details, preview_url



# =================== 新增：Gradio/命令行主流程 ===================

def process_url(url: str, print_details: bool = False) -> str:
    """核心处理流程：给一个 Civitai URL，抓取信息并写入 output。

    返回状态字符串：成功时 "done~!"，失败时错误提示。
    """
    url = (url or "").strip()
    if not url.startswith("http"):
        return "failed to fetch data. please check the url and try again."

    try:
        details, preview_url = extract_details_from_url(url)

        if print_details:
            for key in TARGET_FIELDS:
                print(f"{key}: {details.get(key, '')}")

        file_name = details.get("File Name", "")
        save_preview_image(preview_url, file_name, proxies=PROXIES, headers=HEADERS)
        save_details_txt(details, url)

        # 只在 GUI 模式（print_details=False）下自动打开 output 文件夹
        if not print_details:
            try:
                script_dir = os.path.dirname(os.path.abspath(__file__))
                output_dir = os.path.join(script_dir, "output")
                os.system(f'open "{output_dir}"')
            except Exception as e:
                print(f"[warn] 无法自动打开 output 文件夹：{e}")

        return "done~!"
    except Exception as e:
        # 终端里保留错误信息，方便调试
        print(f"[error] {e}")
        return "failed to fetch data. please check the url and try again."


def launch_gradio() -> None:
    """启动一个简单的 Gradio 界面。

    - 上方一个文本框输入 Civitai URL
    - 右侧按钮 Export
    - 下方状态文本显示 "done~!" 或错误提示

    注意：为避免本地 127.0.0.1 流量继续走全局代理，这里在 launch 前暂时关闭
    HTTP(S)_PROXY / ALL_PROXY，并设置 NO_PROXY；退出后再恢复环境变量。
    """
    if gr is None:
        raise RuntimeError("Gradio is not installed. 请先运行 `pip install gradio`。")

    def on_export(url: str) -> str:
        return process_url(url, print_details=False)

    with gr.Blocks() as demo:
        gr.Markdown("# Vincenzo")
        gr.HTML(
            """
            <style>
            #export_btn {
                background-color: #fbb03b !important;
                border-color: #fbb03b !important;
                color: white !important;
                font-weight: 600;
                font-size: 1.1rem;
                border-radius: 3px !important;
            }
            #export_btn:hover {
                filter: brightness(0.95);
            }
            </style>
            """
        )

        with gr.Row(equal_height=True):
            url_box = gr.Textbox(
                label="Civitai model webpage URL :",
                lines=1,
                placeholder="enter the model page URL here",
                scale=4,
                container=False,
            )
            export_btn = gr.Button("Export", scale=1, elem_id="export_btn")

        status_box = gr.Textbox(
            show_label=False,
            interactive=False,
            lines=1,
            placeholder="status...",
            container=False,
        )

        export_btn.click(fn=on_export, inputs=url_box, outputs=status_box)

    # ===== 在这里暂时关闭代理环境变量，避免 httpx 访问本地地址时走代理 =====
    proxy_keys = [
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
    ]
    saved_env: Dict[str, Optional[str]] = {k: os.environ.get(k) for k in proxy_keys}
    saved_no_proxy = os.environ.get("NO_PROXY")
    saved_no_proxy_lower = os.environ.get("no_proxy")

    for k in proxy_keys:
        if k in os.environ:
            os.environ.pop(k)

    # 确保本地地址不走代理
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    os.environ["no_proxy"] = "127.0.0.1,localhost"

    try:
        # 自动在默认浏览器中打开 Gradio 页面
        demo.launch(inbrowser=True)
    finally:
        # 恢复原有的代理设置
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

        if saved_no_proxy is None:
            os.environ.pop("NO_PROXY", None)
        else:
            os.environ["NO_PROXY"] = saved_no_proxy

        if saved_no_proxy_lower is None:
            os.environ.pop("no_proxy", None)
        else:
            os.environ["no_proxy"] = saved_no_proxy_lower


def main() -> None:
    """命令行 / GUI 入口：

    - 带 URL 参数：走命令行模式，照旧打印字段并写入文件
    - 不带参数：如果装了 gradio，则启动图形界面；否则给出用法提示
    """
    # 情况 1：命令行带 URL
    if len(sys.argv) >= 2 and sys.argv[1] != "--gui":
        url = sys.argv[1].strip()
        msg = process_url(url, print_details=True)
        # 命令行模式下顺便输出最终状态
        print(msg)
        return

    # 情况 2：显式要求 GUI 或没有参数
    if gr is not None:
        launch_gradio()
    else:
        print("用法：python civitai_details.py <civitai 模型页 URL>\n"
              "或：pip install gradio 后，不带参数运行以启动图形界面。")


if __name__ == "__main__":
    main()