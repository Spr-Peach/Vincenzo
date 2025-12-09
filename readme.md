<p align="center">
  <img src="https://raw.githubusercontent.com/Spr-Peach/Harbor-Hickam/main/vincenzo_screenshot.png" width="720">
</p>
<p align="center">A clean and elegant Civitai model info exporter.</p>

## About Vincenzo

**Vincenzo** is a lightweight utility designed to extract essential information from **Civitai model pages**—including model metadata and a preview image. It solves a common pain point for users who maintain large local model collections:
> *Civitai does not provide a simple way to batch-download model previews and metadata for organizing files locally.*

Vincenzo makes this process effortless. Simply paste a Civitai model URL into the web UI (or run via command line), and it will automatically:

- Fetch detailed metadata from the model page  
- Download the first valid preview image  
- Save both items into the `output/` directory as:

```
output/<model_name>.png  
output/<model_name>.txt
```

### What’s inside the TXT file?

Each exported `.txt` file contains all relevant structured details captured from the Civitai model page, including:

- **Type** (e.g., LoRA, Checkpoint, LoCon, etc.)  
- **Published date**  
- **Base model**  
- **Trigger words** / Usage tips  
- **Hash information**  
- **File name** of the actual model file  
- **Source URL** of the model page  

This ensures you always have a human-readable reference for the model, even without opening Civitai.

### Recommended workflow

After exporting multiple models, it is recommended to **move the generated `.png` and `.txt` files into the same directory where you store the corresponding model files locally**.  
This keeps your model folders organized and makes browsing significantly easier.

### Default image behavior

If a model page contains **no preview images**, Vincenzo will automatically use the bundled `default.png` as a placeholder.  
This guarantees that every export always includes a usable preview image—preventing missing thumbnails in your model library.

### Proxy configuration (optional)

If you access Civitai through a proxy, you can configure it in the `config.json` file:

```
{
  "enable_proxy": true,
  "proxy_host": "127.0.0.1",
  "proxy_port": 7890
}
```

- Set `"enable_proxy": true` to activate proxy routing  
- Adjust `"proxy_host"` and `"proxy_port"` to match your local proxy setup  
- When disabled, all network requests run normally without proxy

---

## Installation

### 1. clone the repository

```bash
git clone https://github.com/Spr-Peach/Vincenzo.git
cd Vincenzo
```

### 2. create and activate a virtual environment
*(recommended: python 3.11 or later)*

#### a. using Python `venv`

```bash
python3.11 -m venv vincenzo
source vincenzo/bin/activate # macos/linux
vincenzo\Scripts\activate # windows
```

#### b. using Conda

```bash
conda create -n vincenzo python=3.11
conda activate vincenzo
```

### 3. install dependencies

```bash
pip install -r requirements.txt
```

---

## Running

### 1. Command-line mode

```bash
python vincenzo.py "<civitai model page url>" # Keep the quotation marks around the URL
```

### 2. Gradio UI mode

```bash
python vincenzo.py
```

*This launches the interactive web interface (default: http://127.0.0.1:7860/).*

---

### Contact

For questions or feedback, feel free to reach out at:  
**10topowerof1000@gmail.com**

### Acknowledgment

Special thanks to **ChatGPT** for the invaluable help throughout the development of *Vincenzo*.