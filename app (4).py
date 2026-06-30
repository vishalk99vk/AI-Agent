"""
============================================================
  AUTOMATION AGENT — One app, one prompt box, many tools
============================================================
Upload your file(s), type what you want in plain English,
and the agent picks the right script from your toolbox and
runs it. No more hunting for the right .py file.

Run with:
    pip install streamlit pandas openpyxl pillow rapidfuzz requests --break-system-packages
    streamlit run app.py
============================================================
"""

import streamlit as st
import pandas as pd
import os, re, csv, math, shutil, zipfile, tempfile, io
from collections import defaultdict
from PIL import Image, UnidentifiedImageError, ImageOps
from learning_engine import (
    load_learned_keywords,
    save_learned_keyword,
    extract_candidate_phrase,
    detect_intent as _engine_detect_intent,
)

st.set_page_config(page_title="Automation Agent", layout="centered")

# ------------------------------------------------------------------
# 1. INTENT DETECTION  — keyword rules -> task id
#    (This is the "brain". No external AI call needed, but you can
#    swap detect_intent() for a real Claude API call later — see
#    the OPTIONAL section at the bottom of this file.)
# ------------------------------------------------------------------

TASKS = {
    "download_images_from_links": {
        "label": "Download images from a list of URLs (.txt)",
        "keywords": ["download image", "url", "link to image", "image link", "download from link", "fetch image"],
        "hint": "Upload 1 .txt file — one image URL per line.",
    },
    "msl_validation": {
        "label": "Validate MSL vs Assortment file (match/mismatch report)",
        "keywords": ["msl", "assortment", "validate", "validation", "match sku", "mismatch"],
        "hint": "Upload 2 files: the Assortment file first, then the MSL file (xlsx/xls/csv).",
    },
    "png_to_jpg_zip": {
        "label": "Convert PNG images inside a ZIP to JPG",
        "keywords": ["png to jpg", "png  jpg", "convert png"],
        "hint": "Upload 1 .zip file containing PNG images.",
    },
    "any_to_jpg_zip": {
        "label": "Convert ANY image format (incl. DNG/RAW) inside a ZIP to JPG",
        "keywords": ["all image", "any image", "raw", "dng", "convert image", "all format", "every image"],
        "hint": "Upload 1 .zip file containing any mix of image formats.",
    },
    "rename_by_parent_folder": {
        "label": "Rename images using their parent folder name (ZIP of folders)",
        "keywords": ["parent folder", "folder name", "rename image", "rename as folder"],
        "hint": "Upload 1 .zip file where images sit inside subfolders (folder name becomes the new image name).",
    },
    "match_images_with_excel": {
        "label": "Pick out images that match names listed in an Excel file (from a ZIP)",
        "keywords": ["match image name", "match image", "image name from excel", "separate image", "filter image"],
        "hint": "Upload 1 .zip of images + 1 Excel file (image names in the first column).",
    },
    "match_shop_id": {
        "label": "Match Shop IDs across multiple Excel files vs a reference file",
        "keywords": ["shop id", "store id", "match shop", "match store"],
        "hint": "Upload your data file(s) plus the reference Excel file LAST (the last Excel you upload is treated as the reference).",
    },
    "match_beat_plan": {
        "label": "Fuzzy-match a column across files vs a Beat Plan reference (handles typos)",
        "keywords": ["beat plan", "fuzzy", "fuzzy match", "missing shop"],
        "hint": "Upload your data file(s) plus the Beat Plan reference file LAST.",
    },
    "cross_join_shop_sku": {
        "label": "Cross-join Shop file × SKU file, auto-split into parts & zip",
        "keywords": ["cross join", "shop x sku", "shop * sku", "split shop", "shop sku combination", "master file"],
        "hint": "Upload 2 files: the Shop file first, then the SKU file.",
    },
}


def detect_intent(prompt: str):
    """Thin wrapper so the rest of app.py can keep calling detect_intent(prompt)
    while the real logic lives in learning_engine.py (a separate file)."""
    return _engine_detect_intent(prompt, TASKS)


# ------------------------------------------------------------------
# 2. TASK IMPLEMENTATIONS (refactored from your original scripts —
#    same logic, just file-object in / file-bytes out instead of
#    tkinter file dialogs).
# ------------------------------------------------------------------

def read_any_table(uploaded_file):
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded_file)
    return pd.read_excel(uploaded_file)


def zip_bytes_of_folder(folder_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root_dir, _, files in os.walk(folder_path):
            for f in files:
                fp = os.path.join(root_dir, f)
                zf.write(fp, arcname=os.path.relpath(fp, folder_path))
    buf.seek(0)
    return buf


# ---- 1. Download images from links --------------------------------
def task_download_images(txt_file):
    import requests
    urls = [l.decode("utf-8").strip() if isinstance(l, bytes) else l.strip()
            for l in txt_file.read().decode("utf-8").splitlines() if l.strip()]
    tmp_dir = tempfile.mkdtemp()
    log = []
    for url in urls:
        try:
            file_name = url.split("/")[-1].split("?")[0]
            out_path = os.path.join(tmp_dir, file_name)
            img_data = requests.get(url, timeout=20).content
            with open(out_path, "wb") as f:
                f.write(img_data)
            log.append(f"✅ Downloaded: {file_name}")
        except Exception as e:
            log.append(f"❌ Failed: {url} → {e}")
    zbuf = zip_bytes_of_folder(tmp_dir)
    shutil.rmtree(tmp_dir, ignore_errors=True)
    return zbuf, "\n".join(log)


# ---- 2. MSL validation ---------------------------------------------
def clean_text(value):
    if pd.isna(value):
        return ""
    return str(value).strip().lower()


def task_msl_validation(assortment_file, msl_file):
    assortment_df = read_any_table(assortment_file)
    msl_df = read_any_table(msl_file)
    assortment_df.columns = assortment_df.columns.str.strip()
    msl_df.columns = msl_df.columns.str.strip()

    for col in ["assortment name", "sku name"]:
        if col not in assortment_df.columns:
            raise Exception(f"Column missing in Assortment file: {col}")
    for col in ["Cat Key", "SKU Name"]:
        if col not in msl_df.columns:
            raise Exception(f"Column missing in MSL file: {col}")

    assortment_df["Cat Key Clean"] = assortment_df["assortment name"].apply(clean_text)
    assortment_df["SKU Clean"] = assortment_df["sku name"].apply(clean_text)
    msl_df["Cat Key Clean"] = msl_df["Cat Key"].apply(clean_text)
    msl_df["SKU Clean"] = msl_df["SKU Name"].apply(clean_text)

    lookup = set(zip(assortment_df["Cat Key Clean"], assortment_df["SKU Clean"]))
    msl_df["Validation Status"] = [
        "MATCH" if (k, s) in lookup else "MISMATCH"
        for k, s in zip(msl_df["Cat Key Clean"], msl_df["SKU Clean"])
    ]

    matched_df = msl_df[msl_df["Validation Status"] == "MATCH"]
    mismatch_df = msl_df[msl_df["Validation Status"] == "MISMATCH"]

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        matched_df.to_excel(writer, sheet_name="Matched_Data", index=False)
        mismatch_df.to_excel(writer, sheet_name="Mismatch_Data", index=False)
    buf.seek(0)
    summary = f"Total: {len(msl_df)} | Matched: {len(matched_df)} | Mismatch: {len(mismatch_df)}"
    return buf, summary


# ---- 3. PNG to JPG from ZIP ----------------------------------------
def task_png_to_jpg(zip_file):
    tmp_dir = tempfile.mkdtemp()
    extract_dir = os.path.join(tmp_dir, "extracted")
    jpg_dir = os.path.join(tmp_dir, "jpg")
    os.makedirs(extract_dir, exist_ok=True)
    os.makedirs(jpg_dir, exist_ok=True)

    with zipfile.ZipFile(zip_file) as zf:
        zf.extractall(extract_dir)

    count = 0
    for root_dir, _, files in os.walk(extract_dir):
        for file in files:
            if file.lower().endswith(".png"):
                with Image.open(os.path.join(root_dir, file)) as img:
                    rgb_img = img.convert("RGB")
                    rgb_img.save(os.path.join(jpg_dir, os.path.splitext(file)[0] + ".jpg"), "JPEG")
                    count += 1

    zbuf = zip_bytes_of_folder(jpg_dir)
    shutil.rmtree(tmp_dir, ignore_errors=True)
    return zbuf, f"Converted {count} PNG files to JPG."


# ---- 4. ANY image format to JPG (incl RAW/DNG) ----------------------
def sanitize_filename(filename):
    return re.sub(r'[\\/*?:"<>|=,&]', "_", filename)


def get_unique_filename(folder, filename):
    base, ext = os.path.splitext(filename)
    counter = 1
    new_name = filename
    while os.path.exists(os.path.join(folder, new_name)):
        new_name = f"{base}_{counter}{ext}"
        counter += 1
    return new_name


def convert_to_jpeg(input_path, output_path):
    ext = os.path.splitext(input_path)[1].lower()
    if ext == ".dng":
        import rawpy, imageio
        with rawpy.imread(input_path) as raw:
            rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=True, output_bps=8)
        imageio.imwrite(output_path, rgb)
    else:
        img = Image.open(input_path)
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "LA"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            img = bg
        else:
            img = img.convert("RGB")
        img.save(output_path, "JPEG", quality=95)


def task_any_to_jpg(zip_file):
    tmp_dir = tempfile.mkdtemp()
    extract_dir = os.path.join(tmp_dir, "extracted")
    jpg_dir = os.path.join(tmp_dir, "jpg")
    os.makedirs(extract_dir, exist_ok=True)
    os.makedirs(jpg_dir, exist_ok=True)

    with zipfile.ZipFile(zip_file) as zf:
        zf.extractall(extract_dir)
    shutil.rmtree(os.path.join(extract_dir, "__MACOSX"), ignore_errors=True)

    converted, skipped = 0, []
    for root_dir, _, files in os.walk(extract_dir):
        for file in files:
            if file.startswith("._"):
                continue
            file_path = os.path.join(root_dir, file)
            safe_name = sanitize_filename(os.path.splitext(file)[0])
            output_name = get_unique_filename(jpg_dir, safe_name + ".jpg")
            output_path = os.path.join(jpg_dir, output_name)
            try:
                convert_to_jpeg(file_path, output_path)
                converted += 1
            except (UnidentifiedImageError, Exception) as e:
                skipped.append(f"{file} → {e}")

    zbuf = zip_bytes_of_folder(jpg_dir)
    shutil.rmtree(tmp_dir, ignore_errors=True)
    log = f"Converted {converted} images." + (f"\nSkipped {len(skipped)} files." if skipped else "")
    return zbuf, log


# ---- 5. Rename images as parent folder name -------------------------
def task_rename_by_parent(zip_file):
    tmp_dir = tempfile.mkdtemp()
    extract_dir = os.path.join(tmp_dir, "extracted")
    out_dir = os.path.join(tmp_dir, "renamed")
    os.makedirs(extract_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)

    with zipfile.ZipFile(zip_file) as zf:
        zf.extractall(extract_dir)

    supported = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".webp")
    total = 0
    for root_dir, _, files in os.walk(extract_dir):
        folder_name = os.path.basename(root_dir)
        if not folder_name:
            continue
        count = 1
        for file in files:
            if file.lower().endswith(supported):
                file_path = os.path.join(root_dir, file)
                try:
                    with Image.open(file_path) as img:
                        img = img.convert("RGB")
                        while True:
                            new_name = f"{folder_name}_{count}.jpg"
                            output_path = os.path.join(out_dir, new_name)
                            if not os.path.exists(output_path):
                                break
                            count += 1
                        img.save(output_path, "JPEG", quality=95)
                        count += 1
                        total += 1
                except Exception:
                    pass

    zbuf = zip_bytes_of_folder(out_dir)
    shutil.rmtree(tmp_dir, ignore_errors=True)
    return zbuf, f"Renamed/processed {total} images."


# ---- 6. Match image names from Excel (ZIP + Excel) -------------------
def task_match_images_excel(zip_file, excel_file):
    tmp_dir = tempfile.mkdtemp()
    extract_dir = os.path.join(tmp_dir, "extracted")
    out_dir = os.path.join(tmp_dir, "matched")
    os.makedirs(extract_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)

    with zipfile.ZipFile(zip_file) as zf:
        zf.extractall(extract_dir)

    df = pd.read_excel(excel_file)
    excel_names = set(df.iloc[:, 0].astype(str).str.lower())

    count = 0
    for root_dir, _, files in os.walk(extract_dir):
        for file in files:
            file_lower = file.lower()
            name_no_ext = os.path.splitext(file_lower)[0]
            if file_lower in excel_names or name_no_ext in excel_names:
                shutil.copy(os.path.join(root_dir, file), os.path.join(out_dir, file))
                count += 1

    zbuf = zip_bytes_of_folder(out_dir)
    shutil.rmtree(tmp_dir, ignore_errors=True)
    return zbuf, f"{count} images matched and copied."


# ---- 7. Match Shop ID from Store ID (multiple files + reference) -----
def task_match_shop_id(data_files, reference_file, shop_col=None):
    ref_df = pd.read_excel(reference_file)
    if not shop_col or shop_col not in ref_df.columns:
        # try to auto-detect a column with "shop" or "store" in its name
        guess = next((c for c in ref_df.columns if "shop" in c.lower() or "store" in c.lower()), None)
        shop_col = guess or ref_df.columns[0]
    ref_ids = set(ref_df[shop_col].astype(str).str.strip())

    matched_rows = []
    for f in data_files:
        try:
            df = read_any_table(f)
        except Exception:
            continue
        possible_col = shop_col if shop_col in df.columns else next(
            (c for c in df.columns if "shop" in c.lower() or "store" in c.lower()), df.columns[0]
        )
        df[possible_col] = df[possible_col].astype(str).str.strip()
        matched = df[df[possible_col].isin(ref_ids)].copy()
        if not matched.empty:
            matched["Source_File"] = f.name
            matched_rows.append(matched)

    if not matched_rows:
        return None, "No matching Shop IDs found."

    final_df = pd.concat(matched_rows, ignore_index=True)
    buf = io.BytesIO()
    final_df.to_excel(buf, index=False)
    buf.seek(0)
    return buf, f"Matched {len(final_df)} rows across {len(data_files)} file(s)."


# ---- 8. Fuzzy match vs Beat Plan reference ---------------------------
def task_match_beat_plan(data_files, reference_file, column, ref_column, threshold=90):
    from rapidfuzz import process, fuzz

    combined = set()
    for f in data_files:
        try:
            df = read_any_table(f)
        except Exception:
            continue
        if column not in df.columns:
            continue
        combined.update(df[column].dropna().astype(str).str.lower().str.strip())

    ref_df = read_any_table(reference_file)
    reference = set(ref_df[ref_column].dropna().astype(str).str.lower().str.strip())

    ref_index = defaultdict(list)
    for r in reference:
        if r:
            ref_index[r[0]].append(r)

    missing = []
    for val in combined:
        if not val or val in reference:
            continue
        candidates = ref_index.get(val[0], [])
        if not candidates:
            missing.append(val)
        else:
            _, score, _ = process.extractOne(val, candidates, scorer=fuzz.token_sort_ratio)
            if score < threshold:
                missing.append(val)

    buf = io.BytesIO()
    pd.DataFrame(missing, columns=[column]).to_excel(buf, index=False)
    buf.seek(0)
    return buf, f"Missing / unmatched values: {len(missing)}"


# ---- 9. Cross-join Shop x SKU -----------------------------------------
def task_cross_join(shop_file, sku_file, threshold=700000):
    shop_df = read_any_table(shop_file)
    sku_df = read_any_table(sku_file)

    total_skus = len(sku_df)
    shops_per_file = max(1, math.ceil(threshold / total_skus))
    shop_records = shop_df.to_dict("records")
    sku_records = sku_df.to_dict("records")
    total_shops = len(shop_records)

    header = list(shop_df.columns) + [c for c in sku_df.columns if c not in shop_df.columns]
    tmp_dir = tempfile.mkdtemp()
    csv_files = []
    batch_size = 5000

    for part, start in enumerate(range(0, total_shops, shops_per_file), start=1):
        end = min(start + shops_per_file, total_shops)
        current_shops = shop_records[start:end]
        out_path = os.path.join(tmp_dir, f"Output_Shop_SKU_Part{part}.csv")
        csv_files.append(out_path)
        with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writeheader()
            buffer = []
            for shop in current_shops:
                for sku in sku_records:
                    row = {col: shop.get(col, "") for col in shop_df.columns}
                    for col in sku_df.columns:
                        if col not in shop_df.columns:
                            row[col] = sku.get(col, "")
                    buffer.append(row)
                    if len(buffer) >= batch_size:
                        writer.writerows(buffer)
                        buffer.clear()
            if buffer:
                writer.writerows(buffer)

    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fp in csv_files:
            zf.write(fp, os.path.basename(fp))
    zbuf.seek(0)
    shutil.rmtree(tmp_dir, ignore_errors=True)
    return zbuf, f"SKU rows: {total_skus} | Shops/file: {shops_per_file} | Total shops: {total_shops} | Parts: {len(csv_files)}"


# ------------------------------------------------------------------
# 3. UI
# ------------------------------------------------------------------

st.title("🤖 Automation Agent")
st.caption("Type what you want, upload the file(s), and the right tool runs automatically.")

with st.expander("ℹ️ What can this agent do?"):
    for t in TASKS.values():
        st.markdown(f"- **{t['label']}** — _{t['hint']}_")

col_a, col_b = st.columns([5, 1])
with col_a:
    prompt = st.text_area(
        "What do you want to do?",
        placeholder="e.g. 'Match image names from this excel against the zip of photos' or 'convert all images in this zip to jpg'",
    )
with col_b:
    st.write("")
    st.write("")
    if st.button("🔄 Reset"):
        st.session_state.clear()
        st.rerun()

uploaded_files = st.file_uploader(
    "Upload your file(s) (zip / xlsx / csv / txt — upload all files this task needs)",
    accept_multiple_files=True,
)

detected, confidence = detect_intent(prompt) if prompt else (None, None)

if prompt:
    if detected and confidence == "high":
        st.success(f"Detected task: **{TASKS[detected]['label']}**")
    elif detected and confidence == "low":
        st.warning(
            f"Your prompt matches more than one task — best guess is "
            f"**{TASKS[detected]['label']}**. Please confirm below."
        )
    else:
        st.warning("Couldn't confidently detect a task from your prompt — please pick one manually below.")

task_id = st.selectbox(
    "Confirm / override task",
    options=list(TASKS.keys()),
    format_func=lambda k: TASKS[k]["label"],
    index=list(TASKS.keys()).index(detected) if detected else 0,
)

st.info(f"📎 Needed files for this task: {TASKS[task_id]['hint']}")

if task_id == "cross_join_shop_sku" and uploaded_files:
    st.warning(
        "Cross-join multiplies Shop rows × SKU rows — with large files this can produce "
        "millions of rows and take a while. Make sure that's really what you want."
    )

run = st.button("🚀 Run")

def file_by_ext(files, ext_list):
    return [f for f in files if f.name.lower().endswith(ext_list)]

if run:
    if not uploaded_files:
        st.error("Please upload at least one file.")
        st.stop()

    try:
        with st.spinner("Working on it..."):
            zips = file_by_ext(uploaded_files, (".zip",))
            excels = file_by_ext(uploaded_files, (".xlsx", ".xls"))
            csvs = file_by_ext(uploaded_files, (".csv",))
            txts = file_by_ext(uploaded_files, (".txt",))
            tables = excels + csvs

            result_buf, log = None, ""
            out_name = "output"

            if task_id == "download_images_from_links":
                if not txts:
                    raise Exception("Please upload a .txt file with image URLs.")
                result_buf, log = task_download_images(txts[0])
                out_name = "downloaded_images.zip"

            elif task_id == "msl_validation":
                if len(tables) < 2:
                    raise Exception("Please upload both the Assortment file and the MSL file.")
                result_buf, log = task_msl_validation(tables[0], tables[1])
                out_name = "Validated_MSL_Output.xlsx"

            elif task_id == "png_to_jpg_zip":
                if not zips:
                    raise Exception("Please upload a .zip file.")
                result_buf, log = task_png_to_jpg(zips[0])
                out_name = "converted_jpg.zip"

            elif task_id == "any_to_jpg_zip":
                if not zips:
                    raise Exception("Please upload a .zip file.")
                result_buf, log = task_any_to_jpg(zips[0])
                out_name = "converted_jpg.zip"

            elif task_id == "rename_by_parent_folder":
                if not zips:
                    raise Exception("Please upload a .zip file (containing subfolders of images).")
                result_buf, log = task_rename_by_parent(zips[0])
                out_name = "renamed_images.zip"

            elif task_id == "match_images_with_excel":
                if not zips or not tables:
                    raise Exception("Please upload both a .zip of images and an Excel file with image names.")
                result_buf, log = task_match_images_excel(zips[0], tables[0])
                out_name = "matched_images.zip"

            elif task_id == "match_shop_id":
                if not tables:
                    raise Exception("Please upload the data file(s) and a reference Excel file.")
                reference_file = tables[-1]
                data_files = tables[:-1] if len(tables) > 1 else tables
                result_buf, log = task_match_shop_id(data_files, reference_file)
                out_name = "Matched_Shop_IDs.xlsx"

            elif task_id == "match_beat_plan":
                if len(tables) < 2:
                    raise Exception("Please upload data file(s) and a reference (Beat Plan) Excel file.")
                reference_file = tables[-1]
                data_files = tables[:-1]
                # let the user pick columns
                sample_df = read_any_table(data_files[0])
                ref_df = read_any_table(reference_file)
                col = st.selectbox("Column to compare from data files", sample_df.columns)
                ref_col = st.selectbox("Column to compare from reference file", ref_df.columns)
                if st.button("Confirm columns and run fuzzy match"):
                    result_buf, log = task_match_beat_plan(data_files, reference_file, col, ref_col)
                    out_name = "Missing_Values.xlsx"

            elif task_id == "cross_join_shop_sku":
                if len(tables) < 2:
                    raise Exception("Please upload both the Shop file and the SKU file.")
                result_buf, log = task_cross_join(tables[0], tables[1])
                out_name = "Output_Shop_SKU_All_Files.zip"

        if result_buf is not None:
            st.success("Done!")
            st.text(log)
            mime = "application/zip" if out_name.endswith(".zip") else \
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            st.download_button("⬇️ Download Result", data=result_buf, file_name=out_name, mime=mime)
            st.session_state["last_run"] = {"prompt": prompt, "task_id": task_id}
        elif log:
            st.info(log)

    except Exception as e:
        st.error(f"Error: {e}")

# ------------------------------------------------------------------
# 4. LEARNING / FEEDBACK LOOP
#    The agent remembers corrections so the same kind of prompt is
#    routed correctly next time, without touching the code.
# ------------------------------------------------------------------

if "last_run" in st.session_state and st.session_state["last_run"]["prompt"] == prompt:
    last = st.session_state["last_run"]
    st.divider()
    st.subheader("🧠 Help the agent learn")
    st.caption("Did it pick the right task for your wording? Your answer is saved so similar prompts are detected automatically next time.")

    fb_col1, fb_col2 = st.columns(2)
    with fb_col1:
        if st.button("👍 Yes, correct task"):
            phrase = extract_candidate_phrase(last["prompt"])
            save_learned_keyword(last["task_id"], phrase)
            st.toast(f"Learned: '{phrase}' → {TASKS[last['task_id']]['label']}")
            del st.session_state["last_run"]

    with fb_col2:
        wrong = st.button("👎 No, wrong task")

    if wrong:
        st.session_state["correcting"] = True

    if st.session_state.get("correcting"):
        correct_task = st.selectbox(
            "What should it have been?",
            options=list(TASKS.keys()),
            format_func=lambda k: TASKS[k]["label"],
            key="correction_select",
        )
        if st.button("Save correction"):
            phrase = extract_candidate_phrase(last["prompt"])
            save_learned_keyword(correct_task, phrase)
            st.toast(f"Learned: '{phrase}' → {TASKS[correct_task]['label']}")
            st.session_state["correcting"] = False
            del st.session_state["last_run"]

with st.expander("📚 What has the agent learned so far?"):
    learned = load_learned_keywords()
    if not learned:
        st.write("Nothing learned yet — run a task and give feedback to start teaching it.")
    else:
        for task_id_l, phrases in learned.items():
            if phrases:
                st.markdown(f"**{TASKS[task_id_l]['label']}**: {', '.join(phrases)}")
